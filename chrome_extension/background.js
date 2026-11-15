/* A narrow native bridge for one user-requested YouTube tab. */
let nativePort = null;
let connecting = false;
const HOST = 'com.jarvis.music';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function connectHost() {
  if (nativePort || connecting) return;
  connecting = true;
  try {
    const port = chrome.runtime.connectNative(HOST);
    nativePort = port;
    port.onMessage.addListener(async message => {
      if (!message || !/^[a-f0-9]{32}$/.test(message.id || '')) return;
      let result;
      try {
        if (message.action === 'open') result = await openVideo(message.video_id);
        else if (message.action === 'pause') result = await pauseVideo();
        else result = {code: 'tab_error'};
      } catch (_) {
        result = {code: 'tab_error'};
      }
      try { port.postMessage({id: message.id, result}); } catch (_) { /* host disconnected */ }
    });
    port.onDisconnect.addListener(() => {
      void chrome.runtime.lastError;
      if (nativePort === port) nativePort = null;
      setTimeout(connectHost, 5000);
    });
  } catch (_) {
    nativePort = null;
  } finally {
    connecting = false;
  }
}

function videoIdFromUrl(url) {
  try {
    const value = new URL(url);
    if (value.protocol !== 'https:' || !['www.youtube.com', 'youtube.com', 'm.youtube.com'].includes(value.hostname)) return null;
    return value.searchParams.get('v');
  } catch (_) { return null; }
}

async function inspect(tabId, action) {
  const response = await chrome.scripting.executeScript({
    target: {tabId},
    func: (action) => {
      const error = document.querySelector('.ytp-error-content-wrap');
      const visibleError = !!(error && error.getClientRects().length && getComputedStyle(error).visibility !== 'hidden');
      const player = document.querySelector('video');
      const ad = !!document.querySelector('.ad-showing');
      if (!player) return {present: false, error: visibleError, ad};
      if (action === 'play' && player.paused && !player.error) player.play().catch(() => {});
      if (action === 'pause') player.pause();
      return {present: true, error: visibleError || !!player.error, ad, paused: player.paused,
              muted: player.muted || player.volume === 0, time: player.currentTime};
    },
    args: [action],
  });
  return response[0]?.result || {present: false};
}

async function openVideo(videoId) {
  if (!/^[A-Za-z0-9_-]{11}$/.test(videoId || '')) return {opened: false, code: 'tab_error'};
  const {jarvisMusicTab: prior} = await chrome.storage.session.get('jarvisMusicTab');
  let tab;
  if (prior && Number.isInteger(prior.id)) {
    try {
      const current = await chrome.tabs.get(prior.id);
      if (videoIdFromUrl(current.url) === prior.videoId) {
        tab = await chrome.tabs.update(prior.id, {url: 'https://www.youtube.com/watch?v=' + videoId, active: true});
      }
    } catch (_) { /* tab was closed */ }
  }
  if (!tab) tab = await chrome.tabs.create({url: 'https://www.youtube.com/watch?v=' + videoId, active: true});
  if (!Number.isInteger(tab.id)) return {opened: false, code: 'tab_error'};
  await chrome.storage.session.set({jarvisMusicTab: {id: tab.id, videoId}});
  let previous = null;
  let sawAd = false;
  for (let i = 0; i < 22; i++) {
    await sleep(1000);
    let info;
    try {
      const current = await chrome.tabs.get(tab.id);
      if (videoIdFromUrl(current.url) !== videoId) continue;
      info = await inspect(tab.id, 'play');
    } catch (_) { continue; }
    if (info.error) return {opened: true, playing: false, code: 'youtube_error'};
    if (info.ad) { sawAd = true; previous = null; continue; }
    if (info.present && !info.paused && typeof info.time === 'number') {
      if (info.muted) return {opened: true, playing: false, code: 'muted'};
      if (previous !== null && info.time - previous > 0.3) return {opened: true, playing: true};
      previous = info.time;
    } else previous = null;
  }
  return {opened: true, playing: false, code: sawAd ? 'ad' : 'not_playing'};
}

async function pauseVideo() {
  const {jarvisMusicTab: tab} = await chrome.storage.session.get('jarvisMusicTab');
  if (!tab || !Number.isInteger(tab.id) || !/^[A-Za-z0-9_-]{11}$/.test(tab.videoId || '')) return {paused: false, code: 'no_tab'};
  try {
    const current = await chrome.tabs.get(tab.id);
    if (videoIdFromUrl(current.url) !== tab.videoId) return {paused: false, code: 'no_tab'};
    const info = await inspect(tab.id, 'pause');
    if (info.present && info.paused) return {paused: true};
    return {paused: false, code: 'tab_error'};
  } catch (_) { return {paused: false, code: 'no_tab'}; }
}

chrome.runtime.onInstalled.addListener(connectHost);
chrome.runtime.onStartup.addListener(connectHost);
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'jarvis-reconnect') connectHost(); });
chrome.alarms.create('jarvis-reconnect', {periodInMinutes: 0.5});
connectHost();

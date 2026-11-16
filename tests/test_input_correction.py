"""Corrector determinista de entrada (tipeo y ASR)."""
import input_correction


def test_obvious_typos_snap_to_command_vocabulary():
    assert 'archivos' in input_correction.correct('elimina los archivs pdf que creaste')
    assert 'musica' in input_correction.correct('ponme muica por favor')
    assert 'enviar' in input_correction.correct('quiero enviqr un correo')


def test_classic_asr_mishearings():
    assert input_correction.correct('alo') == 'hola'


def test_names_paths_and_extensions_are_untouched():
    assert 'Trujillo' in input_correction.correct('clima en Trujillo mañana')
    assert 'a mama' in input_correction.correct('quiero enviqr un correo a mama')  # no «maxima»
    assert input_correction.correct('~/Documentos/Prueba.pdf') == '~/Documentos/Prueba.pdf'
    assert 'https://example.com' in input_correction.correct('abre https://example.com')


def test_punctuation_is_preserved_around_corrections():
    assert 'archivos,' in input_correction.correct('elimina los archivs, por favor')


def test_long_prose_is_left_alone_for_the_model():
    text = 'cuentame un chiste largo sobre programadores y sus problemas habituales con punteros y memoria en sistemas embebidos modernos de verdad'
    assert input_correction.correct(text) == text


def test_folded_form_is_available_for_matching():
    assert input_correction.fold('Mañana a las 8') == 'manana a las 8'

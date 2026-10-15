package com.samuelpart.jarvispro.gemini

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/**
 * Modelos de datos de la API de Gemini (`generativelanguage.googleapis.com/v1beta`).
 *
 * Se escriben a mano en vez de usar el SDK oficial por dos razones concretas:
 *   1. El SDK de Android para Gemini quedó deprecado a favor de Firebase AI
 *      Logic, que obliga a meter Firebase en el proyecto. Aquí sobra.
 *   2. Controlamos el payload byte a byte, que es lo que permite limpiar los
 *      esquemas de herramientas (ver `ToolSchema.kt`) y conservar las firmas de
 *      pensamiento de Gemini 3.
 *
 * Todos los campos opcionales tienen valor por defecto para que
 * `encodeDefaults = false` no los envíe cuando no se usan.
 */

@Serializable
data class Content(
    /** "user" o "model". Las respuestas a una función también van como "user". */
    val role: String? = null,
    val parts: List<Part> = emptyList(),
)

@Serializable
data class Part(
    val text: String? = null,
    val functionCall: FunctionCall? = null,
    val functionResponse: FunctionResponse? = null,
    /**
     * Gemini 3 firma cada llamada a función y EXIGE que se devuelva tal cual en
     * el turno siguiente. Si se pierde, la API responde 400 "thought signature
     * is missing". Por eso el agente reenvía los `parts` del modelo sin tocarlos.
     */
    val thoughtSignature: String? = null,
    val thought: Boolean? = null,
)

@Serializable
data class FunctionCall(
    val name: String = "",
    val args: JsonObject? = null,
    val id: String? = null,
)

@Serializable
data class FunctionResponse(
    val name: String = "",
    val response: JsonObject = JsonObject(emptyMap()),
    val id: String? = null,
)

@Serializable
data class ToolDeclaration(
    val name: String,
    val description: String,
    val parameters: JsonObject,
)

@Serializable
data class ToolsBlock(
    val functionDeclarations: List<ToolDeclaration>,
)

@Serializable
data class GenerationConfig(
    val temperature: Double? = null,
    val maxOutputTokens: Int? = null,
    val topP: Double? = null,
)

@Serializable
data class GeminiRequest(
    val contents: List<Content>,
    val tools: List<ToolsBlock>? = null,
    val systemInstruction: Content? = null,
    val generationConfig: GenerationConfig? = null,
)

@Serializable
data class GeminiResponse(
    val candidates: List<Candidate> = emptyList(),
    val usageMetadata: Usage? = null,
    val promptFeedback: PromptFeedback? = null,
)

@Serializable
data class Candidate(
    val content: Content? = null,
    val finishReason: String? = null,
)

@Serializable
data class Usage(
    val promptTokenCount: Int = 0,
    val candidatesTokenCount: Int = 0,
    val totalTokenCount: Int = 0,
)

@Serializable
data class PromptFeedback(val blockReason: String? = null)

/** Cuerpo de error de la API: `{"error": {"code":…, "message":…, "status":…}}`. */
@Serializable
data class ApiErrorBody(val error: ApiError? = null)

@Serializable
data class ApiError(
    val code: Int = 0,
    val message: String = "",
    val status: String = "",
)

/** Respuesta de `GET /v1beta/models`. */
@Serializable
data class ModelsListResponse(val models: List<ModelInfo> = emptyList())

@Serializable
data class ModelInfo(
    /** Llega como "models/gemini-3.8-flash". */
    val name: String = "",
    val displayName: String? = null,
    val description: String? = null,
    /** Solo se listan los que sirven para generar contenido. */
    val supportedGenerationMethods: List<String> = emptyList(),
) {
    /** "models/gemini-3.8-flash" -> "gemini-3.8-flash" */
    val shortName: String get() = name.substringAfterLast('/')
}

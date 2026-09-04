package com.carebridge.elder.data

import android.util.Log
import com.carebridge.elder.BuildConfig
import com.google.android.gms.tasks.Tasks
import com.google.firebase.auth.FirebaseAuth
import com.squareup.moshi.Json
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import java.util.concurrent.TimeUnit

private const val TAG = "CareBridge"

/**
 * Every field the elder does not strictly need is nullable with a default.
 *
 * Moshi's reflective adapter throws on an absent key *and* on an explicit null,
 * and the API genuinely sends both: a medication with no name yet comes back as
 * `"medication_name": null`. A throw here surfaces to the elder as "Cannot
 * reach CareBridge right now" on a phone that reached it perfectly well.
 */
data class Reminder(
    @Json(name = "event_id") val eventId: String,
    @Json(name = "medication_id") val medicationId: String? = null,
    @Json(name = "medication_name") val medicationName: String? = null,
    val dose: String? = null,
    @Json(name = "food_instruction_text") val foodInstruction: String? = null,
    val notes: String? = null,
    val status: String? = null,
    val attempt: Int = 0,
    @Json(name = "elder_language") val language: String? = null,
    @Json(name = "photo_url") val photoUrl: String? = null,
    @Json(name = "caregiver_audio_url") val caregiverAudioUrl: String? = null,
    @Json(name = "has_photo") val hasPhoto: Boolean = false,
    @Json(name = "has_caregiver_audio") val hasCaregiverAudio: Boolean = false,
)

data class ActiveReminder(
    val active: Boolean = false,
    /**
     * The first open dose, kept for compatibility.
     *
     * The app reads [reminders] instead: an evening is rarely one tablet, and
     * taking only this field is why an elder with three medicines due at once
     * saw one, answered it, and had the other two escalate to her family
     * unanswered — for doses she was never shown.
     */
    val reminder: Reminder? = null,
    /** Every dose open right now, oldest first. The server already sends it. */
    val reminders: List<Reminder> = emptyList(),
    val remaining: Int = 0,
)

data class SnoozeBody(val minutes: Int)

data class DeclineBody(val reason: String?)

data class ChatBody(
    @Json(name = "elder_id") val elderId: String,
    @Json(name = "event_id") val eventId: String?,
    val message: String,
)

data class ChatReply(
    val reply: String,
    @Json(name = "tool_calls") val toolCalls: List<String> = emptyList(),
    // Only sent when a dose is actually in play, so its absence is normal.
    @Json(name = "event_status") val eventStatus: String? = null,
)

data class StatusReply(val status: String)

data class RegisterDeviceBody(
    @Json(name = "fcm_token") val fcmToken: String,
    val platform: String = "ANDROID",
    val label: String? = null,
)

/**
 * The spoken code, and this phone's address, in one unauthenticated call.
 *
 * Registering the token here rather than afterwards means the phone is
 * reachable the moment it is paired. The alternative needs a signed-in call the
 * app cannot make yet, leaving a window in which the family is told the phone
 * is paired and no reminder can arrive at it.
 */
data class RedeemBody(
    val code: String,
    @Json(name = "fcm_token") val fcmToken: String?,
    val platform: String = "ANDROID",
    val label: String? = null,
)

data class RedeemReply(
    @Json(name = "elder_id") val elderId: String,
    @Json(name = "elder_name") val elderName: String,
    @Json(name = "custom_token") val customToken: String? = null,
    @Json(name = "device_registered") val deviceRegistered: Boolean = false,
)

interface CareBridgeApi {

    @GET("api/reminders/active")
    suspend fun activeReminder(): ActiveReminder

    @GET("api/medication-events/{eventId}")
    suspend fun event(@Path("eventId") eventId: String): Reminder

    @POST("api/reminders/{eventId}/taken")
    suspend fun markTaken(@Path("eventId") eventId: String): StatusReply

    @POST("api/reminders/{eventId}/snooze")
    suspend fun snooze(
        @Path("eventId") eventId: String,
        @Body body: SnoozeBody,
    ): StatusReply

    @POST("api/reminders/{eventId}/decline")
    suspend fun decline(
        @Path("eventId") eventId: String,
        @Body body: DeclineBody,
    ): StatusReply

    @POST("api/agent/chat")
    suspend fun chat(@Body body: ChatBody): ChatReply

    /**
     * `api/devices` is the caregiver's endpoint and refuses a phone. This is
     * the one a paired device may call for itself — the elder it belongs to
     * comes from its own credentials, so it cannot sign anyone else up.
     */
    @POST("api/devices/mine")
    suspend fun registerDevice(@Body body: RegisterDeviceBody)

    @POST("api/pairing/redeem")
    suspend fun redeemPairingCode(@Body body: RedeemBody): RedeemReply
}

object ApiClient {

    /** Set once the device is paired; every request carries it. */
    @Volatile
    var elderId: String? = null

    /**
     * Signs in as the elder with the token pairing handed back.
     *
     * Called once at pairing. Firebase keeps the session on the device from
     * then on and refreshes it itself, so the custom token — which is only
     * valid for an hour — never needs storing.
     */
    suspend fun signIn(customToken: String): Boolean = runCatching {
        Tasks.await(
            FirebaseAuth.getInstance().signInWithCustomToken(customToken),
            30,
            TimeUnit.SECONDS,
        )
        true
    }.getOrElse {
        Log.w(TAG, "sign_in_failed ${it.message}")
        false
    }

    fun isSignedIn(): Boolean = FirebaseAuth.getInstance().currentUser != null

    /**
     * Every request carries the elder's Firebase ID token.
     *
     * Blocking on the token is correct here: OkHttp interceptors already run
     * off the main thread, and a request sent without it comes back 401,
     * which the elder only ever sees as "cannot reach CareBridge".
     *
     * `X-Elder-Id` used to stand in for this. The deployed API ignores that
     * header completely, so it was never authenticating anything.
     */
    private fun idToken(forceRefresh: Boolean): String? {
        val user = FirebaseAuth.getInstance().currentUser ?: return null
        return runCatching {
            Tasks.await(user.getIdToken(forceRefresh), 20, TimeUnit.SECONDS).token
        }.getOrNull()
    }

    private val identity = Interceptor { chain ->
        fun send(token: String?) = chain.proceed(
            chain.request().newBuilder()
                .apply { token?.let { addHeader("Authorization", "Bearer $it") } }
                .build()
        )

        val response = send(idToken(forceRefresh = false))

        // A cached token that the server has expired or revoked. Worth one
        // forced refresh before giving up, because the alternative is a
        // reminder the elder cannot answer.
        if (response.code != 401) return@Interceptor response

        Log.i(TAG, "token_rejected retrying with a fresh one")
        response.close()
        send(idToken(forceRefresh = true))
    }

    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    val api: CareBridgeApi by lazy {
        Retrofit.Builder()
            .baseUrl(BuildConfig.API_BASE_URL.trimEnd('/') + "/")
            .client(OkHttpClient.Builder().addInterceptor(identity).build())
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(CareBridgeApi::class.java)
    }

    /** Media paths come back relative when GCS signing is unavailable. */
    fun absolute(url: String): String =
        if (url.startsWith("http")) url
        else BuildConfig.API_BASE_URL.trimEnd('/') + url

    /**
     * Headers for fetching a photo or a recording.
     *
     * A signed storage URL needs none. The relative fallback is served by our
     * own API and needs the elder's token — and the image loader and the media
     * player each use their own HTTP stack, so neither passes through the
     * interceptor above. That is exactly how the photo and the voice went
     * missing while every other call worked.
     */
    fun mediaHeaders(url: String): Map<String, String> {
        // Decided by ORIGIN, not by whether the string happens to start with
        // "http". Callers resolve a URL with absolute() before handing it to a
        // player, so by the time it arrived here every URL looked absolute and
        // this returned nothing — the token was never attached, and the 401 it
        // was written to prevent came back anyway.
        val ours = !url.startsWith("http") || url.startsWith(apiOrigin)
        if (!ours) return emptyMap()

        return idToken(forceRefresh = false)
            ?.let { mapOf("Authorization" to "Bearer $it") }
            ?: emptyMap()
    }

    /** Scheme and host of our own API, for telling our URLs from storage's. */
    private val apiOrigin: String by lazy {
        runCatching {
            val base = java.net.URI(BuildConfig.API_BASE_URL)
            "${base.scheme}://${base.host}"
        }.getOrDefault(BuildConfig.API_BASE_URL.trimEnd('/'))
    }

    /** An image loader that authenticates the same way the API client does. */
    val imageLoaderClient: OkHttpClient by lazy {
        OkHttpClient.Builder().addInterceptor(identity).build()
    }
}

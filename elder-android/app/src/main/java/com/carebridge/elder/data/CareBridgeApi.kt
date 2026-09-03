package com.carebridge.elder.data

import com.carebridge.elder.BuildConfig
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
    val reminder: Reminder? = null,
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

    private val identity = Interceptor { chain ->
        val request = chain.request().newBuilder()
            .apply { elderId?.let { addHeader("X-Elder-Id", it) } }
            .build()
        chain.proceed(request)
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
}

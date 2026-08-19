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

data class Reminder(
    @Json(name = "event_id") val eventId: String,
    @Json(name = "medication_id") val medicationId: String,
    @Json(name = "medication_name") val medicationName: String,
    val dose: String,
    @Json(name = "food_instruction_text") val foodInstruction: String,
    val notes: String?,
    val status: String,
    val attempt: Int,
    @Json(name = "photo_url") val photoUrl: String?,
    @Json(name = "caregiver_audio_url") val caregiverAudioUrl: String?,
    @Json(name = "has_photo") val hasPhoto: Boolean,
    @Json(name = "has_caregiver_audio") val hasCaregiverAudio: Boolean,
)

data class ActiveReminder(
    val active: Boolean,
    val reminder: Reminder?,
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
    @Json(name = "tool_calls") val toolCalls: List<String>,
    @Json(name = "event_status") val eventStatus: String?,
)

data class StatusReply(val status: String)

data class RegisterDeviceBody(
    @Json(name = "elder_id") val elderId: String,
    @Json(name = "fcm_token") val fcmToken: String,
    val platform: String = "ANDROID",
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

    @POST("api/devices")
    suspend fun registerDevice(@Body body: RegisterDeviceBody)
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

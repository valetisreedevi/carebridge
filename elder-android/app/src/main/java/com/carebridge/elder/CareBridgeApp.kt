package com.carebridge.elder

import android.app.Application
import coil.Coil
import coil.ImageLoader
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.Pairing
import com.carebridge.elder.notify.ensureReminderChannel

class CareBridgeApp : Application() {

    override fun onCreate() {
        super.onCreate()
        // Both are needed before a notification can arrive, and a notification
        // can arrive before any activity has been created.
        ensureReminderChannel(this)
        Pairing.load(this)

        // Photos come back either as a signed storage URL or as a path served
        // by our own API, which needs the elder's token. Coil's default loader
        // sends no headers, so the second kind silently 401s and the medicine
        // shows with no picture — the one thing an elder recognises it by.
        Coil.setImageLoader(
            ImageLoader.Builder(this)
                .okHttpClient { ApiClient.imageLoaderClient }
                .build()
        )
    }
}

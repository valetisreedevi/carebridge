package com.carebridge.elder

import android.app.Application
import com.carebridge.elder.data.Pairing
import com.carebridge.elder.notify.ensureReminderChannel

class CareBridgeApp : Application() {

    override fun onCreate() {
        super.onCreate()
        // Both are needed before a notification can arrive, and a notification
        // can arrive before any activity has been created.
        ensureReminderChannel(this)
        Pairing.load(this)
    }
}

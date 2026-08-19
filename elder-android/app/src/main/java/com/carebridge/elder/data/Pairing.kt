package com.carebridge.elder.data

import android.content.Context
import androidx.core.content.edit

/** Which elder this phone belongs to. Set once, during setup. */
object Pairing {

    private const val PREFS = "carebridge"
    private const val KEY_ELDER_ID = "elder_id"

    fun load(context: Context): String? {
        val stored = context
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_ELDER_ID, null)
        ApiClient.elderId = stored
        return stored
    }

    fun save(context: Context, elderId: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit {
            putString(KEY_ELDER_ID, elderId)
        }
        ApiClient.elderId = elderId
    }
}

package app.wayward

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : Activity() {

    private lateinit var web: WebView
    private lateinit var status: TextView
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        status = TextView(this).apply {
            text = "Starting Wayward…\n\nThe first launch unpacks the game and can take a minute."
            gravity = Gravity.CENTER
            setTextColor(Color.parseColor("#C9A558"))
            setBackgroundColor(Color.parseColor("#100E0A"))
            textSize = 16f
        }
        web = WebView(this).apply {
            visibility = View.GONE
            setBackgroundColor(Color.parseColor("#100E0A"))
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            webViewClient = WebViewClient() // keep navigation inside the app
            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(
                    view: WebView?,
                    callback: ValueCallback<Array<Uri>>,
                    params: FileChooserParams,
                ): Boolean {
                    fileCallback?.onReceiveValue(null)
                    fileCallback = callback
                    return try {
                        @Suppress("DEPRECATION")
                        startActivityForResult(params.createIntent(), RC_FILE_CHOOSER)
                        true
                    } catch (e: Exception) {
                        fileCallback = null
                        false
                    }
                }
            }
        }
        setContentView(FrameLayout(this).apply {
            setBackgroundColor(Color.parseColor("#100E0A"))
            addView(web)
            addView(status)
        })

        waitForServerThenLoad()
    }

    private fun waitForServerThenLoad() {
        Thread({
            val deadline = System.currentTimeMillis() + STARTUP_TIMEOUT_MS
            var up = false
            while (!up && System.currentTimeMillis() < deadline) {
                up = healthy()
                if (!up) Thread.sleep(500)
            }
            runOnUiThread {
                if (up) {
                    status.visibility = View.GONE
                    web.visibility = View.VISIBLE
                    web.loadUrl(APP_URL)
                } else {
                    status.text = "Wayward's backend didn't come up.\n\nForce-close the app and try again."
                }
            }
        }, "wayward-health").start()
    }

    private fun healthy(): Boolean = try {
        val conn = URL("$APP_URL/health").openConnection() as HttpURLConnection
        conn.connectTimeout = 1000
        conn.readTimeout = 1000
        val ok = conn.responseCode == 200
        conn.disconnect()
        ok
    } catch (e: Exception) {
        false
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == RC_FILE_CHOOSER) {
            fileCallback?.onReceiveValue(
                WebChromeClient.FileChooserParams.parseResult(resultCode, data)
            )
            fileCallback = null
        } else {
            @Suppress("DEPRECATION")
            super.onActivityResult(requestCode, resultCode, data)
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack()
        else {
            @Suppress("DEPRECATION")
            super.onBackPressed()
        }
    }

    companion object {
        private const val APP_URL = "http://127.0.0.1:8000"
        private const val RC_FILE_CHOOSER = 71
        private const val STARTUP_TIMEOUT_MS = 180_000L
    }
}

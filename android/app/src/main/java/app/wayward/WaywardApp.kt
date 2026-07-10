package app.wayward

import android.app.Application
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.zip.ZipInputStream

/**
 * Starts the embedded Python backend. The repo's server/ package and the
 * built client ride along as assets/wayward.zip; they're extracted to
 * filesDir/wayward once per app version. Everything under server/data
 * (worlds, saves, characters) and server/portraits (uploads) is preserved
 * across updates — only code and the client bundle are refreshed.
 */
class WaywardApp : Application() {

    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        Thread({
            try {
                val root = prepareTree()
                Python.getInstance().getModule("serverhost")
                    .callAttr("start", root.absolutePath)
            } catch (e: Exception) {
                Log.e(TAG, "backend failed to start", e)
            }
        }, "wayward-server").apply { isDaemon = true }.start()
    }

    private fun prepareTree(): File {
        val root = File(filesDir, "wayward")
        val marker = File(filesDir, "wayward.version")
        val pkg = packageManager.getPackageInfo(packageName, 0)
        @Suppress("DEPRECATION")
        val zipLen = assets.openFd(ASSET_ZIP).use { it.length }
        val stamp = "${pkg.versionName}-${pkg.versionCode}-$zipLen"

        if (root.isDirectory && marker.isFile && marker.readText() == stamp) return root

        // Refresh code, keep user data: wipe client/ entirely and everything in
        // server/ except data/ and portraits/ (runtime portrait uploads).
        File(root, "client").deleteRecursively()
        File(root, "server").listFiles()?.forEach { child ->
            if (child.name != "data" && child.name != "portraits") child.deleteRecursively()
        }

        ZipInputStream(assets.open(ASSET_ZIP).buffered()).use { zin ->
            val rootPath = root.canonicalPath + File.separator
            var entry = zin.nextEntry
            while (entry != null) {
                val out = File(root, entry.name)
                if (!out.canonicalPath.startsWith(rootPath)) {
                    throw SecurityException("zip entry escapes extraction root: ${entry.name}")
                }
                if (entry.isDirectory) {
                    out.mkdirs()
                } else {
                    out.parentFile?.mkdirs()
                    out.outputStream().use { zin.copyTo(it) }
                }
                entry = zin.nextEntry
            }
        }
        marker.writeText(stamp)
        return root
    }

    companion object {
        private const val TAG = "Wayward"
        private const val ASSET_ZIP = "wayward.zip"
    }
}

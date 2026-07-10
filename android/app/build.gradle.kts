plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// The app embeds the whole repo's server/ package plus the production-built
// client (client/dist) as a single zip asset, extracted to filesDir on first
// launch. CI builds the client before Gradle runs.
val repoRoot: File = rootProject.projectDir.parentFile
val waywardAssetsDir = layout.buildDirectory.dir("generated/waywardAssets")

val bundleWaywardAssets = tasks.register<Zip>("bundleWaywardAssets") {
    archiveFileName.set("wayward.zip")
    destinationDirectory.set(waywardAssetsDir)
    from(repoRoot) {
        include("server/**")
        exclude("server/data/**", "server/.venv/**", "**/__pycache__/**")
        include("client/dist/**")
    }
    doFirst {
        check(File(repoRoot, "client/dist/index.html").isFile) {
            "client/dist is missing — run `npm run build` in client/ first"
        }
    }
}

android {
    namespace = "app.wayward"
    compileSdk = 34

    defaultConfig {
        applicationId = "app.wayward"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    androidResources {
        noCompress += "zip" // keep the asset openFd-able (it's already compressed)
    }

    sourceSets["main"].assets.srcDir(waywardAssetsDir)

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

tasks.named("preBuild") { dependsOn(bundleWaywardAssets) }

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            // pydantic v2 (Rust core) has no Android wheels — the server carries
            // a v1 compat shim (server/api/schemas.py). Everything else is pure
            // Python except greenlet, which Chaquopy's repo provides.
            install("pydantic==1.10.19")
            install("fastapi==0.115.12")
            install("uvicorn==0.30.6")
            install("sqlalchemy==2.0.36")
            install("greenlet==3.0.1") // newest Android build in Chaquopy's repo
            install("aiosqlite==0.20.0")
            install("httpx==0.28.1")
            install("python-multipart==0.0.9")
        }
    }
}

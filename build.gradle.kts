plugins {
    java
    application
    id("me.champeau.jmh") version "0.7.2"
    jacoco
}

import org.gradle.internal.os.OperatingSystem
import org.gradle.api.GradleException
import java.io.File

group = "com.localengine"
version = "1.0.0"

java {
    sourceCompatibility = JavaVersion.VERSION_21
    targetCompatibility = JavaVersion.VERSION_21
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("info.picocli:picocli:4.7.6")
    annotationProcessor("info.picocli:picocli-codegen:4.7.6")
    implementation("com.fasterxml.jackson.core:jackson-databind:2.17.0")
    implementation("com.fasterxml.jackson.datatype:jackson-datatype-jsr310:2.17.0")
    implementation("org.xerial:sqlite-jdbc:3.45.1.0")
    implementation("org.slf4j:slf4j-api:2.0.12")
    implementation("ch.qos.logback:logback-classic:1.5.3")
    
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
    
    jmh("org.openjdk.jmh:jmh-core:1.37")
    jmh("org.openjdk.jmh:jmh-generator-annprocess:1.37")
}

application {
    mainClass.set("com.localengine.cli.MainCommand")
}

tasks.test {
    useJUnitPlatform()
    finalizedBy(tasks.jacocoTestReport)
}

tasks.jacocoTestReport {
    dependsOn(tasks.test)
    reports {
        xml.required.set(true)
        html.required.set(true)
    }
}

tasks.jacocoTestCoverageVerification {
    violationRules {
        rule {
            limit {
                minimum = "0.80".toBigDecimal() // 最低80%覆盖率，符合规范要求
            }
        }
    }
}

tasks.withType<JavaCompile> {
    options.encoding = "UTF-8"
    options.compilerArgs.add("-parameters")
}

tasks.register<Exec>("packageAppImage") {
    group = "distribution"
    description = "使用 jpackage 生成可分发 app-image"
    dependsOn("installDist")

    val os = OperatingSystem.current()
    val javaHome = System.getenv("JAVA_HOME")
    val appImageRootDir = layout.buildDirectory.dir("distributions/appimage").get().asFile
    val appImageOutputDir = File(appImageRootDir, "LocalSearchEnginePortable")
    val jpackageBinary = if (os.isWindows) {
        if (javaHome.isNullOrBlank()) "jpackage.exe" else "$javaHome\\bin\\jpackage.exe"
    } else {
        if (javaHome.isNullOrBlank()) "jpackage" else "$javaHome/bin/jpackage"
    }

    doFirst {
        if (appImageOutputDir.exists()) {
            val deleted = appImageOutputDir.deleteRecursively()
            if (!deleted) {
                throw GradleException("无法覆盖已有 app-image，请先关闭 $appImageOutputDir 中正在运行的程序后重试")
            }
        }
    }

    commandLine(
        jpackageBinary,
        "--type", "app-image",
        "--name", "LocalSearchEnginePortable",
        "--input", layout.buildDirectory.dir("install/local-search-engine/lib").get().asFile.absolutePath,
        "--main-jar", tasks.jar.get().archiveFileName.get(),
        "--main-class", "com.localengine.cli.MainCommand",
        "--dest", appImageRootDir.absolutePath
    )
}

tasks.register<Exec>("packageExe") {
    group = "distribution"
    description = "在 Windows 上使用 jpackage 生成 EXE 安装包"
    dependsOn("installDist")
    onlyIf { OperatingSystem.current().isWindows }

    val javaHome = System.getenv("JAVA_HOME")
    val jpackageBinary = if (javaHome.isNullOrBlank()) "jpackage.exe" else "$javaHome\\bin\\jpackage.exe"

    doFirst {
        delete(layout.buildDirectory.file("distributions/LocalSearchEngine-1.0.0.exe").get().asFile)
    }

    commandLine(
        jpackageBinary,
        "--type", "exe",
        "--name", "LocalSearchEngine",
        "--input", layout.buildDirectory.dir("install/local-search-engine/lib").get().asFile.absolutePath,
        "--main-jar", tasks.jar.get().archiveFileName.get(),
        "--main-class", "com.localengine.cli.MainCommand",
        "--dest", layout.buildDirectory.dir("distributions").get().asFile.absolutePath,
        "--win-console"
    )
}

tasks.register<Zip>("packagePortableZip") {
    group = "distribution"
    description = "将 app-image 打包为可直接分发的 zip"
    dependsOn("packageAppImage")

    from(layout.buildDirectory.dir("distributions/appimage/LocalSearchEnginePortable")) {
        into("LocalSearchEnginePortable")
    }
    destinationDirectory.set(layout.buildDirectory.dir("distributions"))
    archiveFileName.set("LocalSearchEnginePortable-${project.version}.zip")
}

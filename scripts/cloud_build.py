#!/usr/bin/env python3
"""Build in the Codex cloud snapshot with writable caches and the supplied proxy."""
import os, pathlib, shutil, subprocess, urllib.parse

root = pathlib.Path(__file__).resolve().parents[1]
tools = pathlib.Path('/workspace/.tools')
(tools/'java-home').mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.update(DOTNET_CLI_HOME=str(tools/'dotnet-home'), NUGET_PACKAGES=str(tools/'nuget'),
           DOTNET_CLI_TELEMETRY_OPTOUT='1', ANDROID_USER_HOME=str(tools/'android-user'))
dotnet = str(tools/'dotnet/dotnet') if (tools/'dotnet/dotnet').exists() else shutil.which('dotnet')
if not dotnet: raise SystemExit('Install .NET SDK 8 first; see README.md')
env['BWW_DOTNET'] = dotnet

def run(args, cwd=root): subprocess.run(args, cwd=cwd, env=env, check=True)
run([dotnet, 'restore', 'server', '--locked-mode'])
run([dotnet, 'build', 'server', '-c', 'Release', '--no-restore'])
run(['python3', 'tests/integration.py'])
if (tools/'jdk/bin/jlink').exists(): env['JAVA_HOME'] = str(tools/'jdk')
if (tools/'android-sdk').exists(): env['ANDROID_HOME'] = str(tools/'android-sdk')
if not env.get('ANDROID_HOME'): raise SystemExit('Set ANDROID_HOME to an installed Android SDK; see README.md')
gradle = str(tools/'gradle-8.9/bin/gradle') if (tools/'gradle-8.9/bin/gradle').exists() else str(root/'android/gradlew')
args = [gradle, '--no-daemon', '--console=plain', '-g', str(tools/'gradle-cache')]
if pathlib.Path('/etc/ssl/certs/java/cacerts').exists():
    args += ['-Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts']
args += ['-Duser.home=' + str(tools/'java-home')]
proxy = urllib.parse.urlsplit(env.get('HTTPS_PROXY', ''))
if proxy.hostname:
    for scheme in ('https', 'http'):
        args += [f'-D{scheme}.proxyHost={proxy.hostname}', f'-D{scheme}.proxyPort={proxy.port or 80}']
run(args + ['assembleDebug', 'testDebugUnitTest', 'lintDebug'], root/'android')
print('C# build, protocol integration tests, Android APK build and Android lint completed.')

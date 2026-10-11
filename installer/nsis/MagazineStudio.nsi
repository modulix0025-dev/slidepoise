; ModuleX Magazine Studio installer (NSIS 3, Unicode) - per-user, no admin rights.
; Replaces Inno Setup (whose author requests a paid licence for commercial use).
; NSIS is zlib/libpng-licensed, free for commercial use, and builds on Linux
; (makensis), so the cloud and ubuntu-latest can produce the Windows installer.
;
; Conventions copied from the operator's MarketX installer (P157):
;   * per-user, PrivilegesRequired=lowest  ->  RequestExecutionLevel user
;   * fixed program dir OUTSIDE C:\<project> so an agent with project access
;     cannot modify the program itself (no directory page)
;   * Arabic wizard, WebView2 check, graceful stop of the old engine on upgrade
;   * uninstall asks before deleting data, default NO
;
; Two flavours from one script (brief 6.10):
;   FLAVOUR=online (default) -> ModuleX-MagazineStudio-Setup-<ver>.exe
;       small; LibreOffice / fonts / shape packs are fetched on demand by the app
;       (installer/downloads.json: pinned sha256, resumable, Arabic progress).
;   FLAVOUR=full -> ModuleX-MagazineStudio-Setup-<ver>-Full.exe
;       offline; OFFLINE_DIR (LibreOffice MSI, font vault, shape packs) goes to
;       $INSTDIR\offline. When PowerPoint is absent, LibreOffice is unpacked
;       WITHOUT admin rights by an MSI administrative extraction (msiexec /a).
;
; Build (Linux or Windows):
;   makensis -INPUTCHARSET UTF8 -DAPP_VER=0.2.0 -DSRC_DIR=<pyinstaller one-folder dir> MagazineStudio.nsi
;   makensis -INPUTCHARSET UTF8 -DAPP_VER=0.2.0 -DSRC_DIR=<dir> -DFLAVOUR=full -DOFFLINE_DIR=<dir> MagazineStudio.nsi
;
; Command line of the produced installer:
;   /S            silent (uninstall data question answers its default: No)
;   /RELAUNCH=1   start the Studio after a silent install (used by the updater and rollback)

Unicode true
ManifestDPIAware true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!ifndef APP_VER
  !define APP_VER "0.0.0"
!endif
!ifndef VI_VER
  !define VI_VER "${APP_VER}.0"
!endif
!ifndef SRC_DIR
  !error "SRC_DIR must point at the PyInstaller one-folder build"
!endif
!ifndef OUT_DIR
  !define OUT_DIR "out"
!endif
!ifndef FLAVOUR
  !define FLAVOUR "online"
!endif

!define APP_NAME "ModuleX Magazine Studio"
!define APP_EXE "ModuleX Magazine Studio.exe"
!define CLI_EXE "mxstudio-cli.exe"
!define APP_ID "{7F41B915-3B66-4225-836B-E52016D9E01E}"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
!define WEBVIEW2_GUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!define DATA_DIR "$LOCALAPPDATA\ModuleX\MagazineStudio"
!define KEEP_DIR "${DATA_DIR}\update\installers"
!define LO_MSI "libreoffice\LibreOffice_Win_x86-64.msi"

!if "${FLAVOUR}" == "full"
  !ifndef OFFLINE_DIR
    !error "FLAVOUR=full needs OFFLINE_DIR (LibreOffice MSI, font vault, shape packs)"
  !endif
  !define SETUP_NAME "ModuleX-MagazineStudio-Setup-${APP_VER}-Full.exe"
!else if "${FLAVOUR}" == "online"
  !define SETUP_NAME "ModuleX-MagazineStudio-Setup-${APP_VER}.exe"
!else
  !error "FLAVOUR must be online or full"
!endif

Name "${APP_NAME}"
OutFile "${OUT_DIR}\${SETUP_NAME}"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
BrandingText "ModuleX"
VIProductVersion "${VI_VER}"
VIAddVersionKey /LANG=0 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=0 "CompanyName" "ModuleX"
VIAddVersionKey /LANG=0 "FileDescription" "${APP_NAME} Setup (${FLAVOUR})"
VIAddVersionKey /LANG=0 "FileVersion" "${APP_VER}"
VIAddVersionKey /LANG=0 "ProductVersion" "${APP_VER}"
VIAddVersionKey /LANG=0 "LegalCopyright" "ModuleX"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "أهلًا بيك في مثبّت استوديو المجلات"
!if "${FLAVOUR}" == "full"
  !define MUI_WELCOMEPAGE_TEXT "هنثبّت «مديول إكس · استوديو المجلات» لحسابك بس، من غير صلاحيات مدير.$\r$\n$\r$\nالنسخة دي كاملة (Full): فيها LibreOffice وخزنة الخطوط وحزم الأشكال، ومش محتاجة إنترنت.$\r$\n$\r$\nالبرنامج بيتحط في فولدر برّه C:\المشروع، ومساحة العمل بتختارها في أول تشغيل."
!else
  !define MUI_WELCOMEPAGE_TEXT "هنثبّت «مديول إكس · استوديو المجلات» لحسابك بس، من غير صلاحيات مدير.$\r$\n$\r$\nالنسخة دي صغيرة (أونلاين): لو محتاجين LibreOffice أو الخطوط هننزّلهم بعدين من أول تشغيل، بملفات متثبّتة البصمة.$\r$\n$\r$\nالبرنامج بيتحط في فولدر برّه C:\المشروع، ومساحة العمل بتختارها في أول تشغيل."
!endif
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "افتح مديول إكس · استوديو المجلات"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Arabic"

Var RemoveData
Var Relaunch

Function WebView2Installed
  ; leaves "1" or "0" on the stack
  ClearErrors
  ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
  ${If} $0 == ""
    ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
  ${EndIf}
  ${If} $0 != ""
  ${AndIf} $0 != "0.0.0.0"
    Push "1"
  ${Else}
    Push "0"
  ${EndIf}
FunctionEnd

Function PowerPointInstalled
  ; leaves "1" or "0" on the stack (same keys as mxstudio/firstrun/office.py)
  ReadRegStr $0 HKCR "PowerPoint.Application\CurVer" ""
  ${If} $0 == ""
    ReadRegStr $0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE" ""
  ${EndIf}
  ${If} $0 == ""
    ReadRegStr $0 HKCU "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE" ""
  ${EndIf}
  ${If} $0 != ""
    Push "1"
  ${Else}
    Push "0"
  ${EndIf}
FunctionEnd

Function StopOld
  ; graceful stop of a running Studio before files are replaced (hidden, waits)
  ${If} ${FileExists} "$INSTDIR\${CLI_EXE}"
    nsExec::Exec '"$INSTDIR\${CLI_EXE}" shutdown'
    Pop $0
  ${ElseIf} ${FileExists} "$INSTDIR\${APP_EXE}"
    nsExec::Exec '"$INSTDIR\${APP_EXE}" --shutdown'
    Pop $0
  ${EndIf}
FunctionEnd

Function .onInit
  StrCpy $Relaunch "0"
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "/RELAUNCH=" $R1
  ${IfNot} ${Errors}
    StrCpy $Relaunch $R1
  ${EndIf}
  Call WebView2Installed
  Pop $0
  ${If} $0 != "1"
    MessageBox MB_ICONSTOP|MB_OK "استوديو المجلات محتاج «Microsoft Edge WebView2 Runtime» ومش لاقيه على الجهاز.$\r$\nنزّله من الرابط الرسمي وبعدين شغّل المثبّت تاني:$\r$\nhttps://developer.microsoft.com/microsoft-edge/webview2/" /SD IDOK
    Abort
  ${EndIf}
  Call StopOld
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${SRC_DIR}\*.*"
!if "${FLAVOUR}" == "full"
  SetOutPath "$INSTDIR\offline"
  File /r "${OFFLINE_DIR}\*.*"
  SetOutPath "$INSTDIR"
!endif
  WriteINIStr "$INSTDIR\install.ini" "install" "flavour" "${FLAVOUR}"
  WriteINIStr "$INSTDIR\install.ini" "install" "version" "${APP_VER}"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"

  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APP_VER}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "ModuleX"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegStr HKCU "${UNINST_KEY}" "Flavour" "${FLAVOUR}"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

!if "${FLAVOUR}" == "online"
  ; keep this installer for one-click rollback (mxstudio/update/state.py reads KEEP_DIR)
  CreateDirectory "${KEEP_DIR}"
  ${If} "$EXEPATH" != "${KEEP_DIR}\${SETUP_NAME}"
    CopyFiles /SILENT "$EXEPATH" "${KEEP_DIR}\${SETUP_NAME}"
  ${EndIf}
!endif

  ; icon cache refresh (same as MarketX: ie4uinit -show), hidden
  nsExec::Exec '"$SYSDIR\ie4uinit.exe" -show'
  Pop $0
SectionEnd

Section "Office engine"
  Call PowerPointInstalled
  Pop $0
  ${If} $0 == "1"
    DetailPrint "لقينا PowerPoint — هنستخدمه للتصدير."
  ${ElseIf} ${FileExists} "$INSTDIR\libreoffice\.mxs-extracted"
    DetailPrint "LibreOffice متجهّز من قبل."
!if "${FLAVOUR}" == "full"
  ${ElseIf} ${FileExists} "$INSTDIR\offline\${LO_MSI}"
    DetailPrint "مفيش PowerPoint — بنفك LibreOffice من غير صلاحيات مدير (msiexec /a)…"
    CreateDirectory "$INSTDIR\libreoffice"
    CreateDirectory "${DATA_DIR}\logs"
    nsExec::Exec 'msiexec.exe /a "$INSTDIR\offline\${LO_MSI}" /qn TARGETDIR="$INSTDIR\libreoffice" /L*v "${DATA_DIR}\logs\libreoffice-admin-extract.log"'
    Pop $0
    ${If} $0 == "0"
      FileOpen $1 "$INSTDIR\libreoffice\.mxs-extracted" w
      FileWrite $1 "msi_admin_extract"
      FileClose $1
      DetailPrint "LibreOffice جاهز."
    ${Else}
      DetailPrint "فك LibreOffice ما نجحش ($0) — الدكتور هيعرض «إصلاح» في أول تشغيل."
    ${EndIf}
!endif
  ${Else}
    DetailPrint "مفيش PowerPoint — LibreOffice هيتنزّل من أول تشغيل (الدكتور ← إصلاح)."
  ${EndIf}
SectionEnd

Function .onInstSuccess
  ${If} ${Silent}
  ${AndIf} $Relaunch == "1"
    Exec '"$INSTDIR\${APP_EXE}"'
  ${EndIf}
FunctionEnd

Function un.onInit
  StrCpy $RemoveData "0"
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "تمسح بيانات استوديو المجلات (الإعدادات والسجل)؟$\r$\nمساحة العمل في C:\المشروع مش هتتلمس.$\r$\nالافتراضي: لأ." /SD IDNO IDNO keep
    StrCpy $RemoveData "1"
  keep:
FunctionEnd

Section "Uninstall"
  ${If} ${FileExists} "$INSTDIR\${CLI_EXE}"
    nsExec::Exec '"$INSTDIR\${CLI_EXE}" shutdown'
    Pop $0
  ${ElseIf} ${FileExists} "$INSTDIR\${APP_EXE}"
    nsExec::Exec '"$INSTDIR\${APP_EXE}" --shutdown'
    Pop $0
  ${EndIf}
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  ${If} $RemoveData == "1"
    RMDir /r "${DATA_DIR}"
  ${EndIf}
SectionEnd

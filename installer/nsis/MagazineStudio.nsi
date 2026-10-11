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
; Build:  makensis -INPUTCHARSET UTF8 -DAPP_VER=0.1.0 -DSRC_DIR=<pyinstaller one-folder dir> MagazineStudio.nsi

Unicode true
ManifestDPIAware true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!ifndef APP_VER
  !define APP_VER "0.0.0"
!endif
!ifndef SRC_DIR
  !error "SRC_DIR must point at the PyInstaller one-folder build"
!endif
!ifndef OUT_DIR
  !define OUT_DIR "out"
!endif

!define APP_NAME "ModuleX Magazine Studio"
!define APP_EXE "ModuleX Magazine Studio.exe"
!define APP_ID "{7F41B915-3B66-4225-836B-E52016D9E01E}"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
!define WEBVIEW2_GUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

Name "${APP_NAME}"
OutFile "${OUT_DIR}\ModuleX-MagazineStudio-Setup-${APP_VER}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
BrandingText "ModuleX"
VIProductVersion "${APP_VER}.0"
VIAddVersionKey /LANG=0 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=0 "CompanyName" "ModuleX"
VIAddVersionKey /LANG=0 "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey /LANG=0 "FileVersion" "${APP_VER}"
VIAddVersionKey /LANG=0 "LegalCopyright" "ModuleX"

!include "MUI2.nsh"
!include "LogicLib.nsh"

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "افتح مديول إكس · استوديو المجلات"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Arabic"

Var RemoveData

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

Function StopOld
  ; graceful stop of a running Studio before files are replaced (hidden, waits)
  IfFileExists "$INSTDIR\${APP_EXE}" 0 done
    nsExec::Exec '"$INSTDIR\${APP_EXE}" --shutdown'
    Pop $0
  done:
FunctionEnd

Function .onInit
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
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  ; icon cache refresh (same as MarketX: ie4uinit -show), hidden
  nsExec::Exec '"$SYSDIR\ie4uinit.exe" -show'
  Pop $0
SectionEnd

Function un.onInit
  StrCpy $RemoveData "0"
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "تمسح بيانات استوديو المجلات (الإعدادات والسجل)؟$\r$\nمساحة العمل في C:\المشروع مش هتتلمس.$\r$\nالافتراضي: لأ." /SD IDNO IDNO keep
    StrCpy $RemoveData "1"
  keep:
FunctionEnd

Section "Uninstall"
  IfFileExists "$INSTDIR\${APP_EXE}" 0 +3
    nsExec::Exec '"$INSTDIR\${APP_EXE}" --shutdown'
    Pop $0
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  ${If} $RemoveData == "1"
    RMDir /r "$LOCALAPPDATA\ModuleX\MagazineStudio"
  ${EndIf}
SectionEnd

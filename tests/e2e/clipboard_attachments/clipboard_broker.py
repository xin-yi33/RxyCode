"""Fail-closed Windows clipboard lease used only by the opted-in E2E suite.

The helper lives in one PowerShell STA so the original IDataObject remains
rooted while test formats are installed. Clipboard contents never leave that
process; evidence contains only a format-set digest and per-format digests.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol
from ctypes import wintypes


_POWERSHELL = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace RxyCodeClipboardE2E -Name ClipboardSequence -MemberDefinition '[DllImport("user32.dll")] public static extern uint GetClipboardSequenceNumber(); [DllImport("user32.dll", SetLastError=true)] public static extern int CountClipboardFormats(); [DllImport("kernel32.dll", EntryPoint="SetLastError")] public static extern void ClearLastError(uint error);'
$Original = $null
$Backup = $null
$Expected = $null
$LastTest = $null
$HasSyntheticWrite = $false
$OriginalSequence = $null
$OwnedSequence = $null
$OwnershipLost = $false
$Ready = $false
$CurrentRequestId = $null
$CurrentStage = 'operation'
$CurrentErrorCode = $null
$CurrentDiagnosticCounts = $null

function Get-Sequence { return [RxyCodeClipboardE2E.ClipboardSequence]::GetClipboardSequenceNumber() }

function Get-ClipboardFormatCount {
  [RxyCodeClipboardE2E.ClipboardSequence]::ClearLastError(0)
  $count = [RxyCodeClipboardE2E.ClipboardSequence]::CountClipboardFormats()
  $error = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
  if ($count -lt 0 -or ($count -eq 0 -and $error -ne 0)) { throw 'clipboard format count could not be verified' }
  return $count
}

function Get-Bytes($value) {
  $script:CurrentStage = 'snapshot-get-bytes'
  if ($null -eq $value) { throw 'clipboard format returned no data' }
  if ($value -is [byte[]]) { return $value }
  if ($value -is [string]) { return [System.Text.Encoding]::UTF8.GetBytes($value) }
  if ($value -is [System.Collections.Specialized.StringCollection]) {
    return [System.Text.Encoding]::UTF8.GetBytes([string]::Join("`0", [string[]]$value))
  }
  if ($value -is [string[]]) {
    return [System.Text.Encoding]::UTF8.GetBytes([string]::Join("`0", $value))
  }
  if ($value -is [System.IO.Stream]) {
    $stream = $value
    $oldPosition = $null
    try {
      if ($stream.CanSeek) { $oldPosition = $stream.Position; $stream.Position = 0 }
      $script:CurrentStage = 'snapshot-copy-stream-bytes'
      $copy = [System.IO.MemoryStream]::new()
      $stream.CopyTo($copy)
      return $copy.ToArray()
    } finally {
      if ($null -ne $oldPosition) { $stream.Position = $oldPosition }
    }
  }
  if ($value -is [System.Drawing.Image]) {
    $memory = [System.IO.MemoryStream]::new()
    try { $value.Save($memory, [System.Drawing.Imaging.ImageFormat]::Png); return $memory.ToArray() }
    finally { $memory.Dispose() }
  }
  throw "unsupported clipboard payload type: $($value.GetType().FullName)"
}

function Get-Sha256Hex([byte[]]$bytes) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $hash = $sha.ComputeHash($bytes)
    return ([System.BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
  } finally { $sha.Dispose() }
}

function Get-Snapshot($dataObject) {
  if ($null -eq $dataObject) {
    $script:CurrentStage = 'snapshot-null-data-object'
    throw 'clipboard data object unavailable'
  }
  $script:CurrentStage = 'snapshot-enumerate-formats'
  $formats = @($dataObject.GetFormats($false) | ForEach-Object { [string]$_ } | Sort-Object -Unique)
  $rows = [System.Collections.Generic.List[string]]::new()
  foreach ($format in $formats) {
    $script:CurrentStage = 'snapshot-get-format-data'
    $value = $dataObject.GetData($format, $false)
    $bytes = Get-Bytes $value
    $script:CurrentStage = 'snapshot-hash-format'
    $sha = Get-Sha256Hex $bytes
    $rows.Add("$format`0$sha`0$($bytes.Length)")
  }
  $script:CurrentStage = 'snapshot-join-format-list'
  $formatText = [string]::Join("`n", $formats)
  $script:CurrentStage = 'snapshot-encode-format-list'
  $formatBytes = [System.Text.Encoding]::UTF8.GetBytes($formatText)
  $script:CurrentStage = 'snapshot-hash-format-list'
  $formatHash = Get-Sha256Hex $formatBytes
  $script:CurrentStage = 'snapshot-join-content-signature'
  $signatureText = [string]::Join("`n", $rows)
  $script:CurrentStage = 'snapshot-encode-content-signature'
  $signatureBytes = [System.Text.Encoding]::UTF8.GetBytes($signatureText)
  $script:CurrentStage = 'snapshot-hash-content-signature'
  $signature = Get-Sha256Hex $signatureBytes
  return @{ format_count = $formats.Count; formats_sha256 = $formatHash; contents_sha256 = $signature }
}

function Get-EmptySnapshot {
  $empty = [byte[]]@()
  $digest = Get-Sha256Hex $empty
  return @{ format_count = 0; formats_sha256 = $digest; contents_sha256 = $digest }
}

function Get-ClipboardSnapshot($dataObject, [int]$nativeCount) {
  if ($nativeCount -eq 0) {
    $managedCount = 0
    if ($null -ne $dataObject) { $managedCount = @($dataObject.GetFormats($false)).Count }
    if ($managedCount -ne 0) {
      $script:CurrentStage = 'snapshot-zero-native-managed-formats'
      $script:CurrentErrorCode = 'zero_native_formats_managed_formats_present'
      $script:CurrentDiagnosticCounts = @{ native_format_count = [int]$nativeCount; managed_format_count = [int]$managedCount }
      throw 'zero native formats disagreed with the clipboard data object'
    }
    return Get-EmptySnapshot
  }
  if ($null -eq $dataObject) {
    $script:CurrentStage = 'snapshot-nonempty-native-managed-formats-empty'
    $script:CurrentErrorCode = 'nonempty_native_formats_managed_formats_empty'
    $script:CurrentDiagnosticCounts = @{ native_format_count = [int]$nativeCount; managed_format_count = 0 }
    throw 'nonempty clipboard had no data object'
  }
  $snapshot = Get-Snapshot $dataObject
  if ($snapshot.format_count -eq 0) {
    $script:CurrentStage = 'snapshot-nonempty-native-managed-formats-empty'
    $script:CurrentErrorCode = 'nonempty_native_formats_managed_formats_empty'
    $script:CurrentDiagnosticCounts = @{ native_format_count = [int]$nativeCount; managed_format_count = [int]$snapshot.format_count }
    throw 'nonempty clipboard formats could not be inspected'
  }
  return $snapshot
}

function Get-StableClipboardSnapshot {
  for ($attempt = 0; $attempt -lt 8; $attempt++) {
    $sequenceBefore = Get-Sequence
    if ($sequenceBefore -eq 0) { throw 'clipboard sequence access could not be verified' }
    $countBefore = Get-ClipboardFormatCount
    $dataObject = [System.Windows.Forms.Clipboard]::GetDataObject()
    $snapshot = Get-ClipboardSnapshot $dataObject $countBefore
    $countAfter = Get-ClipboardFormatCount
    $sequenceAfter = Get-Sequence
    if ($sequenceBefore -eq $sequenceAfter -and $countBefore -eq $countAfter) {
      return @{ snapshot = $snapshot; sequence = $sequenceAfter; format_count = $countAfter; data_object = $dataObject }
    }
    Start-Sleep -Milliseconds 25
  }
  throw 'clipboard did not reach a stable sequence and format count'
}

function Test-SyntheticPayload([string]$operation, $command, $stable) {
  $dataObject = $stable.data_object
  switch ($operation) {
    'set_files' {
      if ($null -eq $dataObject) { return $false }
      $actual = @($dataObject.GetData([System.Windows.Forms.DataFormats]::FileDrop, $false) | ForEach-Object { [string]$_ })
      $expected = @($command.paths | ForEach-Object { [string]$_ })
      if ($actual.Count -ne $expected.Count) { return $false }
      for ($i = 0; $i -lt $actual.Count; $i++) {
        if (-not [string]::Equals($actual[$i], $expected[$i], [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
      }
      return $true
    }
    'set_text' {
      if ($null -eq $dataObject) { return $false }
      $actualText = $dataObject.GetData([System.Windows.Forms.DataFormats]::UnicodeText, $false)
      return [string]::Equals([string]$actualText, [string]$command.text, [System.StringComparison]::Ordinal)
    }
    'set_image' {
      if ($null -eq $dataObject) { return $false }
      $image = $dataObject.GetData([System.Windows.Forms.DataFormats]::Bitmap, $false)
      if ($null -eq $image -or $image.Width -ne [int]$command.width -or $image.Height -ne [int]$command.height) { return $false }
      for ($y = 0; $y -lt $image.Height; $y++) {
        for ($x = 0; $x -lt $image.Width; $x++) {
          $i = ($y * $image.Width + $x) * 3
          $pixel = $image.GetPixel($x, $y)
          if ($pixel.R -ne [int]$command.rgb[$i] -or $pixel.G -ne [int]$command.rgb[$i + 1] -or $pixel.B -ne [int]$command.rgb[$i + 2]) { return $false }
        }
      }
      return $true
    }
    'clear' { return ($stable.snapshot.format_count -eq 0 -and $stable.format_count -eq 0) }
  }
  return $false
}

function Copy-ClipboardValue($value) {
  $script:CurrentStage = 'snapshot-copy-value'
  if ($value -is [string]) { return [string]$value }
  if ($value -is [byte[]]) { return [byte[]]$value.Clone() }
  if ($value -is [System.Collections.Specialized.StringCollection]) {
    $copy = [System.Collections.Specialized.StringCollection]::new()
    foreach ($item in $value) { [void]$copy.Add([string]$item) }
    return $copy
  }
  if ($value -is [string[]]) { return [string[]]$value.Clone() }
  if ($value -is [System.IO.Stream]) { return [System.IO.MemoryStream]::new((Get-Bytes $value)) }
  if ($value -is [System.Drawing.Image]) { return [System.Drawing.Bitmap]::new($value) }
  throw "unsupported clipboard payload type: $($value.GetType().FullName)"
}

function Emit($obj) {
  if ($null -ne $CurrentRequestId) { $obj.request_id = [string]$CurrentRequestId }
  [Console]::Out.WriteLine(($obj | ConvertTo-Json -Compress -Depth 5))
}

while ($null -ne ($line = [Console]::In.ReadLine())) {
  try {
    $command = $line | ConvertFrom-Json
    $CurrentRequestId = [string]$command.request_id
    $CurrentStage = 'operation'
    $CurrentErrorCode = $null
    $CurrentDiagnosticCounts = $null
    switch ([string]$command.op) {
      'ping' {
        Emit (@{ ok = $true; op = 'ping'; process_id = $PID })
        continue
      }
      'snapshot' {
        $CurrentStage = 'snapshot-sequence-before'
        if ($Ready) { throw 'snapshot already completed' }
        $sequenceBefore = Get-Sequence
        if ($sequenceBefore -eq 0) { throw 'clipboard sequence access could not be verified' }
        $CurrentStage = 'snapshot-format-count-before'
        $nativeCount = Get-ClipboardFormatCount
        $CurrentStage = 'snapshot-get-data-object'
        $Original = [System.Windows.Forms.Clipboard]::GetDataObject()
        $Expected = Get-ClipboardSnapshot $Original $nativeCount
        $Backup = [System.Windows.Forms.DataObject]::new()
        if ($nativeCount -gt 0) {
          $CurrentStage = 'snapshot-enumerate-copy-formats'
          foreach ($format in @($Original.GetFormats($false) | ForEach-Object { [string]$_ })) {
            $CurrentStage = 'snapshot-copy-get-format'
            $sourceValue = $Original.GetData($format, $false)
            $copyValue = Copy-ClipboardValue $sourceValue
            $CurrentStage = 'snapshot-copy-set-data'
            $Backup.SetData($format, $false, $copyValue)
          }
        }
        $CurrentStage = 'snapshot-digest-copy'
        $CloneSnapshot = if ($nativeCount -eq 0) { Get-EmptySnapshot } else { Get-Snapshot $Backup }
        if ($CloneSnapshot.format_count -ne $Expected.format_count -or
            $CloneSnapshot.formats_sha256 -ne $Expected.formats_sha256 -or
            $CloneSnapshot.contents_sha256 -ne $Expected.contents_sha256) {
          throw 'an exact in-memory clipboard backup could not be verified'
        }
        $CurrentStage = 'snapshot-stable-readback'
        $Current = Get-StableClipboardSnapshot
        $sequenceAfter = $Current.sequence
        if ($sequenceAfter -ne $sequenceBefore) {
          throw 'clipboard sequence changed while the pre-mutation backup was being verified'
        }
        if ($Current.snapshot.format_count -ne $Expected.format_count -or
            $Current.snapshot.formats_sha256 -ne $Expected.formats_sha256 -or
            $Current.snapshot.contents_sha256 -ne $Expected.contents_sha256 -or
            $Current.format_count -ne $nativeCount) {
          throw 'clipboard changed while the pre-mutation snapshot was being verified'
        }
        $Original = $null
        $OriginalSequence = $sequenceBefore
        $OwnedSequence = $sequenceBefore
        $Ready = $true
        $CurrentStage = 'snapshot-verified'
        Emit (@{ ok = $true; op = 'snapshot'; snapshot = $Expected; sequence = $OriginalSequence; empty_clipboard_verified = ($nativeCount -eq 0) })
      }
      'set_files' {
        if (-not $Ready) { throw 'backup is not verified; clipboard was not changed' }
        if ($OwnershipLost -or (Get-Sequence) -ne $OwnedSequence) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_files'; external_change = $true; sequence = (Get-Sequence) })
          continue
        }
        $sequenceBefore = Get-Sequence
        $files = [System.Collections.Specialized.StringCollection]::new()
        foreach ($path in $command.paths) { [void]$files.Add([string]$path) }
        [System.Windows.Forms.Clipboard]::SetFileDropList($files)
        try { $Stable = Get-StableClipboardSnapshot } catch {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_files'; external_change = $true; sequence = (Get-Sequence) })
          continue
        }
        if (-not (Test-SyntheticPayload 'set_files' $command $Stable)) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_files'; external_change = $true; sequence = $Stable.sequence })
          continue
        }
        $OwnedSequence = $Stable.sequence
        $LastTest = $Stable.snapshot
        $HasSyntheticWrite = $true
        Emit (@{ ok = $true; op = 'set_files'; sequence = $OwnedSequence; snapshot = $LastTest; empty_clipboard_verified = ($LastTest.format_count -eq 0) })
      }
      'set_text' {
        if (-not $Ready) { throw 'backup is not verified; clipboard was not changed' }
        if ($OwnershipLost -or (Get-Sequence) -ne $OwnedSequence) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_text'; external_change = $true; sequence = (Get-Sequence) })
          continue
        }
        $sequenceBefore = Get-Sequence
        [System.Windows.Forms.Clipboard]::SetText([string]$command.text, [System.Windows.Forms.TextDataFormat]::UnicodeText)
        try { $Stable = Get-StableClipboardSnapshot } catch {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_text'; external_change = $true; sequence = (Get-Sequence) })
          continue
        }
        if (-not (Test-SyntheticPayload 'set_text' $command $Stable)) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_text'; external_change = $true; sequence = $Stable.sequence })
          continue
        }
        $OwnedSequence = $Stable.sequence
        $LastTest = $Stable.snapshot
        $HasSyntheticWrite = $true
        Emit (@{ ok = $true; op = 'set_text'; sequence = $OwnedSequence; snapshot = $LastTest; empty_clipboard_verified = ($LastTest.format_count -eq 0) })
      }
      'set_image' {
        if (-not $Ready) { throw 'backup is not verified; clipboard was not changed' }
        if ($OwnershipLost -or (Get-Sequence) -ne $OwnedSequence) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_image'; external_change = $true; sequence = (Get-Sequence) })
          continue
        }
        if ([int]$command.width -le 0 -or [int]$command.height -le 0 -or [int]$command.width * [int]$command.height -gt 2000000 -or @($command.rgb).Count -ne ([int]$command.width * [int]$command.height * 3)) { throw 'synthetic bitmap fixture is outside bounds' }
        $bitmap = [System.Drawing.Bitmap]::new([int]$command.width, [int]$command.height)
        try {
          for ($y = 0; $y -lt $bitmap.Height; $y++) {
            for ($x = 0; $x -lt $bitmap.Width; $x++) {
              $i = ($y * $bitmap.Width + $x) * 3
              $bitmap.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(255, [int]$command.rgb[$i], [int]$command.rgb[$i + 1], [int]$command.rgb[$i + 2]))
            }
          }
          [System.Windows.Forms.Clipboard]::SetImage($bitmap)
        } finally { $bitmap.Dispose() }
        try { $Stable = Get-StableClipboardSnapshot } catch {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_image'; external_change = $true; sequence = (Get-Sequence) })
          continue
        }
        if (-not (Test-SyntheticPayload 'set_image' $command $Stable)) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'set_image'; external_change = $true; sequence = $Stable.sequence })
          continue
        }
        $OwnedSequence = $Stable.sequence
        $LastTest = $Stable.snapshot
        $HasSyntheticWrite = $true
        Emit (@{ ok = $true; op = 'set_image'; sequence = $OwnedSequence; snapshot = $LastTest; empty_clipboard_verified = ($LastTest.format_count -eq 0) })
      }
      'clear' {
        if (-not $Ready) { throw 'backup is not verified; clipboard was not changed' }
        if ($OwnershipLost -or (Get-Sequence) -ne $OwnedSequence) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'clear'; external_change = $true; sequence = (Get-Sequence) })
          continue
        }
        [System.Windows.Forms.Clipboard]::Clear()
        try { $Stable = Get-StableClipboardSnapshot } catch {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'clear'; external_change = $true; sequence = (Get-Sequence) })
          continue
        }
        if (-not (Test-SyntheticPayload 'clear' $command $Stable)) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'clear'; external_change = $true; sequence = $Stable.sequence })
          continue
        }
        $OwnedSequence = $Stable.sequence
        $LastTest = $Stable.snapshot
        $HasSyntheticWrite = $true
        Emit (@{ ok = $true; op = 'clear'; sequence = $OwnedSequence; snapshot = $LastTest; empty_clipboard_verified = $true })
      }
      'restore' {
        if (-not $Ready -or $null -eq $Backup -or $null -eq $Expected) { throw 'verified original clipboard is unavailable' }
        $currentSequence = Get-Sequence
        if ($OwnershipLost -or $currentSequence -ne $OwnedSequence) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'restore'; restored = $false; external_change = $true; original_sequence = $OriginalSequence; owned_sequence = $OwnedSequence; current_sequence = $currentSequence })
          continue
        }
        try { $BeforeRestore = Get-StableClipboardSnapshot } catch {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'restore'; restored = $false; external_change = $true; original_sequence = $OriginalSequence; owned_sequence = $OwnedSequence; current_sequence = (Get-Sequence) })
          continue
        }
        $Owner = if ($null -ne $LastTest) { $LastTest } else { $Expected }
        if ($BeforeRestore.sequence -ne $OwnedSequence -or
            $BeforeRestore.snapshot.format_count -ne $Owner.format_count -or
            $BeforeRestore.snapshot.formats_sha256 -ne $Owner.formats_sha256 -or
            $BeforeRestore.snapshot.contents_sha256 -ne $Owner.contents_sha256) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'restore'; restored = $false; external_change = $true; original_sequence = $OriginalSequence; owned_sequence = $OwnedSequence; current_sequence = (Get-Sequence); expected = $Owner; current = $BeforeRestore.snapshot }); continue
        }
        if (-not $HasSyntheticWrite) {
          Emit (@{ ok = $true; op = 'restore'; restored = $true; snapshot = $BeforeRestore.snapshot; original_sequence = $OriginalSequence; owned_sequence = $OwnedSequence; restored_sequence = $BeforeRestore.sequence; empty_clipboard_verified = ($Expected.format_count -eq 0); clipboard_write_skipped = $true })
          continue
        }
        # Recheck ownership immediately before the one permitted restore write.
        # Win32 does not provide an atomic compare-and-swap for this operation.
        if ((Get-Sequence) -ne $OwnedSequence) {
          $OwnershipLost = $true
          Emit (@{ ok = $false; op = 'restore'; restored = $false; external_change = $true; original_sequence = $OriginalSequence; owned_sequence = $OwnedSequence; current_sequence = (Get-Sequence) })
          continue
        }
        if ($Expected.format_count -eq 0) {
          [System.Windows.Forms.Clipboard]::Clear()
        } else {
          [System.Windows.Forms.Clipboard]::SetDataObject($Backup, $true)
        }
        try { $AfterRestore = Get-StableClipboardSnapshot } catch {
          Emit (@{ ok = $false; op = 'restore'; restored = $false; error_code = 'restore_snapshot_unverified'; expected = $Expected; original_sequence = $OriginalSequence; owned_sequence = $OwnedSequence; current_sequence = (Get-Sequence) })
          continue
        }
        if ($AfterRestore.snapshot.format_count -ne $Expected.format_count -or
            $AfterRestore.snapshot.formats_sha256 -ne $Expected.formats_sha256 -or
            $AfterRestore.snapshot.contents_sha256 -ne $Expected.contents_sha256) {
          Emit (@{ ok = $false; op = 'restore'; restored = $false; error_code = 'restore_digest_mismatch'; expected = $Expected; actual = $AfterRestore.snapshot; original_sequence = $OriginalSequence; owned_sequence = $OwnedSequence; current_sequence = $AfterRestore.sequence })
          continue
        }
        $OwnedSequence = $AfterRestore.sequence
        Emit (@{ ok = $true; op = 'restore'; restored = $true; snapshot = $AfterRestore.snapshot; original_sequence = $OriginalSequence; owned_sequence = $OwnedSequence; restored_sequence = $AfterRestore.sequence; empty_clipboard_verified = ($Expected.format_count -eq 0) })
      }
      'quit' { Emit (@{ ok = $true; op = 'quit' }); [Environment]::Exit(0) }
      default { throw 'unknown clipboard helper command' }
    }
  } catch {
    # Never include exception messages: a third-party formatter could embed
    # clipboard data. The exception class is enough to diagnose a fail-closed path.
    $failedOperation = [string]$command.op
    if ($failedOperation -notin @('snapshot', 'set_files', 'set_text', 'set_image', 'clear', 'restore', 'ping')) { $failedOperation = 'unknown' }
    $failedStage = [string]$CurrentStage
    if ($failedStage -notin @('snapshot-sequence-before', 'snapshot-format-count-before', 'snapshot-get-data-object', 'snapshot-null-data-object', 'snapshot-enumerate-formats', 'snapshot-get-format-data', 'snapshot-hash-format', 'snapshot-join-format-list', 'snapshot-encode-format-list', 'snapshot-hash-format-list', 'snapshot-join-content-signature', 'snapshot-encode-content-signature', 'snapshot-hash-content-signature', 'snapshot-zero-native-managed-formats', 'snapshot-nonempty-native-managed-formats-empty', 'snapshot-enumerate-copy-formats', 'snapshot-copy-get-format', 'snapshot-copy-value', 'snapshot-get-bytes', 'snapshot-copy-stream-bytes', 'snapshot-copy-set-data', 'snapshot-digest-copy', 'snapshot-stable-readback', 'snapshot-verified', 'operation')) { $failedStage = 'operation' }
    $failedCode = if ($CurrentErrorCode -is [string] -and $CurrentErrorCode -match '^[a-z0-9_]{1,64}$') { $CurrentErrorCode } elseif ($failedOperation -eq 'snapshot') { 'clipboard_backup_failed' } else { 'clipboard_operation_failed' }
    $failure = @{ ok = $false; op = $failedOperation; ready = [bool]$Ready; error_type = $_.Exception.GetType().FullName; error_code = $failedCode; error_stage = $failedStage }
    if ($null -ne $CurrentDiagnosticCounts) {
      $failure.native_format_count = [int]$CurrentDiagnosticCounts.native_format_count
      $failure.managed_format_count = [int]$CurrentDiagnosticCounts.managed_format_count
    }
    Emit $failure
  }
}
'''


def _write_helper_script(artifact_dir: Path) -> Path:
    """Write this test's helper source into its unique runtime evidence dir."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    script_path = artifact_dir / f"clipboard-broker-{os.getpid()}-{uuid.uuid4().hex}.ps1"
    with script_path.open("x", encoding="utf-8", newline="\n") as script:
        script.write(_POWERSHELL)
    return script_path.resolve()


def _helper_command(powershell: str, script_path: Path) -> list[str]:
    """Build a short argv vector; never encode the helper body into argv."""
    command = [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-STA",
        # Process-scoped only; no machine/user policy or registry setting is
        # changed by the test.
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path.resolve()),
    ]
    command_line = subprocess.list2cmdline(command)
    utf16_units = len(command_line.encode("utf-16le")) // 2
    if utf16_units + 1 > 32767:
        raise ClipboardSafetyError("clipboard helper command exceeds the Windows CreateProcess limit")
    return command


class ClipboardSafetyError(RuntimeError):
    """The original clipboard could not be proven safe to replace/restore."""


class ExternalClipboardModificationError(ClipboardSafetyError):
    """Another process changed the clipboard during this test's lease."""


class _ClipboardRequestBackend(Protocol):
    """Transport seam for pure state-machine tests; production uses the STA helper."""

    def request(self, row: dict[str, Any]) -> dict[str, Any] | None: ...

    def close(self) -> None: ...


_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_SAFE_ERROR_STAGES = frozenset(
    {
        "snapshot-sequence-before",
        "snapshot-format-count-before",
        "snapshot-get-data-object",
        "snapshot-null-data-object",
        "snapshot-enumerate-formats",
        "snapshot-get-format-data",
        "snapshot-hash-format",
        "snapshot-join-format-list",
        "snapshot-encode-format-list",
        "snapshot-hash-format-list",
        "snapshot-join-content-signature",
        "snapshot-encode-content-signature",
        "snapshot-hash-content-signature",
        "snapshot-zero-native-managed-formats",
        "snapshot-nonempty-native-managed-formats-empty",
        "snapshot-enumerate-copy-formats",
        "snapshot-copy-get-format",
        "snapshot-copy-value",
        "snapshot-get-bytes",
        "snapshot-copy-stream-bytes",
        "snapshot-copy-set-data",
        "snapshot-digest-copy",
        "snapshot-stable-readback",
        "snapshot-verified",
        "operation",
    }
)
_SAFE_ERROR_TOKEN = re.compile(r"[A-Za-z0-9_.+`-]{1,128}\Z")
_SAFE_ERROR_COUNTS = {
    (
        "zero_native_formats_managed_formats_present",
        "snapshot-zero-native-managed-formats",
    ),
    (
        "nonempty_native_formats_managed_formats_empty",
        "snapshot-nonempty-native-managed-formats-empty",
    ),
}


def _verified_snapshot(snapshot: Any, sequence: Any, *, empty_verified: bool) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if set(snapshot) != {"format_count", "formats_sha256", "contents_sha256"}:
        return False
    count = snapshot.get("format_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return False
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not (0 < sequence <= 0xFFFFFFFF):
        return False
    for field in ("formats_sha256", "contents_sha256"):
        digest = snapshot.get(field)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return False
    if count == 0:
        return bool(empty_verified) and (
            snapshot["formats_sha256"] == _EMPTY_SHA256
            and snapshot["contents_sha256"] == _EMPTY_SHA256
        )
    return not empty_verified and (
        snapshot["formats_sha256"] != _EMPTY_SHA256
        and snapshot["contents_sha256"] != _EMPTY_SHA256
    )


class ClipboardSuiteMutex:
    """Fail fast if another opted-in clipboard suite is already active."""

    _NAME = r"Local\RxyCode.ClipboardAttachments.E2E"
    _ERROR_ALREADY_EXISTS = 183

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("the clipboard E2E mutex is Windows-only")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, True, self._NAME)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == self._ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            raise ClipboardSafetyError("another opted-in clipboard E2E process is already active")
        self._kernel32 = kernel32
        self._handle = handle

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle is None:
            return
        self._handle = None
        released = bool(self._kernel32.ReleaseMutex(handle))
        closed = bool(self._kernel32.CloseHandle(handle))
        if not released or not closed:
            raise ClipboardSafetyError("clipboard E2E mutex could not be released cleanly")

    def __enter__(self) -> "ClipboardSuiteMutex":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class ClipboardBroker:
    """One STA clipboard owner; refuses all writes until full backup passes."""

    def __init__(
        self,
        artifact_dir: Path,
        powershell: str = "powershell.exe",
        *,
        _backend: _ClipboardRequestBackend | None = None,
    ) -> None:
        if _backend is None:
            if os.name != "nt":
                raise RuntimeError("the clipboard E2E broker is Windows-only")
            if os.environ.get("RXYCODE_CLIPBOARD_E2E") != "1":
                raise ClipboardSafetyError("set RXYCODE_CLIPBOARD_E2E=1 to opt into the global-clipboard test")
        self.artifact_dir = artifact_dir
        self._backend = _backend
        self._backend_closed = False
        if _backend is None:
            script_path = _write_helper_script(artifact_dir)
            self.process: subprocess.Popen[str] | None = subprocess.Popen(
                _helper_command(powershell, script_path),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="strict",
                bufsize=1,
            )
            self.pid: int | None = int(self.process.pid)
        else:
            self.process = None
            self.pid = None
        self._lock = threading.Lock()
        self._responses: queue.Queue[str | None] = queue.Queue()
        self._response_reader: threading.Thread | None = None
        if self.process is not None:
            self._response_reader = threading.Thread(
                target=self._read_responses,
                name="clipboard-e2e-helper-reader",
                daemon=True,
            )
            self._response_reader.start()
        self._request_seq = 0
        self._ready = False
        self._restored = False
        self._snapshot: dict[str, Any] | None = None
        self._owned_snapshot: dict[str, Any] | None = None
        self._has_synthetic_write = False
        self._restore_external_change = False
        self._external_sequence: int | None = None
        self._restore_verification: dict[str, Any] | None = None
        self._original_sequence: int | None = None
        self._owned_sequence: int | None = None
        self._ownership_lost = False
        self._events: list[dict[str, Any]] = []
        self._construction_failure: dict[str, Any] | None = None
        try:
            result = self._request({"op": "snapshot"}, timeout=10)
            snapshot = result.get("snapshot")
            sequence = result.get("sequence")
            empty_verified = result.get("empty_clipboard_verified") is True
            if result.get("ok") is not True or not _verified_snapshot(
                snapshot, sequence, empty_verified=empty_verified
            ):
                self._construction_failure = self._safe_construction_failure(
                    result,
                    ClipboardSafetyError.__name__,
                    "backup_snapshot_unverified",
                )
                raise ClipboardSafetyError(
                    "clipboard backup could not be verified; no clipboard mutation was attempted"
                )
            self._snapshot = dict(snapshot)
            self._original_sequence = sequence
            self._owned_sequence = self._original_sequence
            self._ready = True
        except BaseException as error:
            if self._construction_failure is None:
                self._construction_failure = self._safe_construction_failure(
                    None, type(error).__name__, "snapshot_request_failed"
                )
            try:
                # Record only error metadata before closing; a failed backup
                # never enters a restore path and never persists its contents.
                self.save_evidence()
            finally:
                self.close_without_restore()
            raise

    @staticmethod
    def _safe_construction_failure(
        result: Any, fallback_type: str, fallback_code: str
    ) -> dict[str, Any]:
        response = result if isinstance(result, dict) else {}
        operation = response.get("op")
        if not isinstance(operation, str) or operation not in {
            "snapshot", "set_files", "set_text", "set_image", "clear", "restore", "ping"
        }:
            operation = "snapshot"
        if not _SAFE_ERROR_TOKEN.fullmatch(fallback_type):
            fallback_type = "RuntimeError"
        error_type = response.get("error_type")
        if not isinstance(error_type, str) or not _SAFE_ERROR_TOKEN.fullmatch(error_type):
            error_type = fallback_type
        error_code = response.get("error_code")
        if not isinstance(error_code, str) or not _SAFE_ERROR_TOKEN.fullmatch(error_code):
            error_code = fallback_code
        error_stage = response.get("error_stage")
        if not isinstance(error_stage, str) or error_stage not in _SAFE_ERROR_STAGES:
            error_stage = "operation"
        failure = {
            "op": operation,
            "error_type": error_type,
            "error_code": error_code,
            "error_stage": error_stage,
            "ready": False,
        }
        if (error_code, error_stage) in _SAFE_ERROR_COUNTS:
            native_count = response.get("native_format_count")
            managed_count = response.get("managed_format_count")
            if all(
                isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 0x7FFFFFFF
                for count in (native_count, managed_count)
            ):
                failure["native_format_count"] = native_count
                failure["managed_format_count"] = managed_count
        return failure

    @property
    def backup(self) -> dict[str, Any]:
        if self._snapshot is None:
            raise ClipboardSafetyError("clipboard backup has not been verified")
        return dict(self._snapshot)

    @property
    def restored(self) -> bool:
        return self._restored

    @property
    def external_modification(self) -> bool:
        return self._ownership_lost

    @property
    def external_sequence(self) -> int | None:
        return self._external_sequence

    def _request(self, row: dict[str, Any], timeout: float = 10) -> dict[str, Any]:
        with self._lock:
            self._request_seq += 1
            request_id = f"clipboard-e2e-{self._request_seq}"
            row = {**row, "request_id": request_id}
            if self._backend is not None:
                if self._backend_closed:
                    raise ClipboardSafetyError("fake clipboard backend is already closed")
                response = self._backend.request(row)
                if not isinstance(response, dict):
                    raise ClipboardSafetyError("clipboard helper returned no valid response object")
            else:
                process = self.process
                if process is None or process.poll() is not None or process.stdin is None or process.stdout is None:
                    raise ClipboardSafetyError("clipboard helper exited before completing the operation")
                process.stdin.write(json.dumps(row, ensure_ascii=False) + "\n")
                process.stdin.flush()
                deadline = time.monotonic() + timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"clipboard helper {row.get('op')} timed out")
                    try:
                        line = self._responses.get(timeout=remaining)
                    except queue.Empty as exc:
                        raise TimeoutError(f"clipboard helper {row.get('op')} timed out") from exc
                    if line is None:
                        raise ClipboardSafetyError("clipboard helper closed its response stream")
                    try:
                        response = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ClipboardSafetyError("clipboard helper returned invalid protocol data") from exc
                    if not isinstance(response, dict):
                        raise ClipboardSafetyError("clipboard helper returned a non-object response")
                    if response.get("request_id") != request_id:
                        # A previous request that timed out may have completed late.
                        continue
                    break
                if not line:
                    raise ClipboardSafetyError("clipboard helper closed its response stream")
            event = {"op": row.get("op"), "ok": bool(response.get("ok"))}
            for key in ("sequence", "owned_sequence", "current_sequence", "restored_sequence"):
                if key in response:
                    event[key] = response[key]
            self._events.append(event)
            if response.get("external_change"):
                self._ownership_lost = True
                sequence = response.get("current_sequence", response.get("sequence"))
                try:
                    self._external_sequence = int(sequence)
                except (TypeError, ValueError):
                    self._external_sequence = None
                if row.get("op") == "restore":
                    self._restore_external_change = True
            return response

    def _read_responses(self) -> None:
        process = self.process
        stream = process.stdout if process is not None else None
        if stream is None:
            self._responses.put(None)
            return
        try:
            for line in stream:
                self._responses.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._responses.put(None)

    def set_files(self, paths: list[Path]) -> None:
        if not self._ready:
            raise ClipboardSafetyError("clipboard backup is not verified; refusing to change it")
        if self._ownership_lost:
            raise ExternalClipboardModificationError("external clipboard change detected; preserving current clipboard")
        if not paths or any(not path.is_file() for path in paths):
            raise ValueError("clipboard file fixtures must already exist")
        result = self._request({"op": "set_files", "paths": [str(path.resolve()) for path in paths]})
        if result.get("external_change"):
            raise ExternalClipboardModificationError("external clipboard change detected; preserving current clipboard")
        self._adopt_test_write(result, "synthetic file-drop clipboard")

    def set_text(self, text: str) -> None:
        if not self._ready:
            raise ClipboardSafetyError("clipboard backup is not verified; refusing to change it")
        if self._ownership_lost:
            raise ExternalClipboardModificationError("external clipboard change detected; preserving current clipboard")
        result = self._request({"op": "set_text", "text": text})
        if result.get("external_change"):
            raise ExternalClipboardModificationError("external clipboard change detected; preserving current clipboard")
        self._adopt_test_write(result, "synthetic Unicode clipboard text")

    def set_image(self, width: int, height: int, rgb: bytes) -> None:
        if not self._ready:
            raise ClipboardSafetyError("clipboard backup is not verified; refusing to change it")
        if self._ownership_lost:
            raise ExternalClipboardModificationError("external clipboard change detected; preserving current clipboard")
        result = self._request({"op": "set_image", "width": width, "height": height, "rgb": list(rgb)})
        if result.get("external_change"):
            raise ExternalClipboardModificationError("external clipboard change detected; preserving current clipboard")
        self._adopt_test_write(result, "synthetic bitmap clipboard")

    def clear(self) -> None:
        if not self._ready:
            raise ClipboardSafetyError("clipboard backup is not verified; refusing to change it")
        if self._ownership_lost:
            raise ExternalClipboardModificationError("external clipboard change detected; preserving current clipboard")
        result = self._request({"op": "clear"})
        if result.get("external_change"):
            raise ExternalClipboardModificationError("external clipboard change detected; preserving current clipboard")
        self._adopt_test_write(result, "synthetic empty clipboard", allow_empty=True)

    def _adopt_test_write(
        self, result: dict[str, Any], description: str, *, allow_empty: bool = False
    ) -> None:
        snapshot = result.get("snapshot")
        sequence = result.get("sequence")
        empty_verified = result.get("empty_clipboard_verified") is True
        if (
            result.get("ok") is not True
            or not _verified_snapshot(snapshot, sequence, empty_verified=empty_verified)
            or (snapshot.get("format_count") == 0) != empty_verified
            or (snapshot.get("format_count") == 0 and not allow_empty)
        ):
            raise ClipboardSafetyError(f"{description} write was not verified by an actual stable snapshot")
        self._owned_sequence = sequence
        self._owned_snapshot = dict(snapshot)
        self._has_synthetic_write = True

    def restore(self) -> dict[str, Any]:
        if not self._ready:
            # A failed backup must cause no destructive operation and should
            # never be mislabeled as a successful restore.
            raise ClipboardSafetyError("original clipboard was not safely backed up")
        if self._ownership_lost:
            self._restore_external_change = True
            raise ExternalClipboardModificationError(
                "external clipboard modification detected; restore was not attempted"
            )
        result = self._request({"op": "restore"}, timeout=12)
        self._restore_external_change = bool(result.get("external_change"))
        self._restore_verification = {
            key: result.get(key)
            for key in (
                "restored", "external_change", "expected", "actual",
                "original_sequence", "owned_sequence", "current_sequence",
                "restored_sequence", "clipboard_write_skipped",
                "empty_clipboard_verified",
            )
            if key in result
        }
        actual_snapshot = result.get("snapshot")
        restored_sequence = result.get("restored_sequence")
        owned_sequence = result.get("owned_sequence")
        write_was_skipped = result.get("clipboard_write_skipped") is True
        self._restored = bool(
            result.get("ok") is True
            and result.get("restored") is True
            and result.get("original_sequence") == self._original_sequence
            and owned_sequence == restored_sequence
            and write_was_skipped is (not self._has_synthetic_write)
            and _verified_snapshot(
                actual_snapshot,
                restored_sequence,
                empty_verified=result.get("empty_clipboard_verified") is True,
            )
            and actual_snapshot == self._snapshot
        )
        if not self._restored and self._restore_external_change:
            raise ExternalClipboardModificationError(
                "external clipboard modification detected; preserved its current contents"
            )
        if not self._restored:
            raise ClipboardSafetyError("clipboard restore could not be verified; suite must stop")
        return dict(actual_snapshot)

    def save_evidence(self) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_dir / "clipboard-safety.json"
        row = {
            "original_snapshot": self._snapshot,
            "restored": self._restored,
            "status": "backup-unverified" if self._construction_failure else (
                "external-modification" if self._ownership_lost else (
                    "restored" if self._restored else "restore-unverified"
                )
            ),
            "ready": self._ready,
            "construction_error": self._construction_failure,
            "external_clipboard_change_detected": self._ownership_lost,
            "original_sequence": self._original_sequence,
            "owned_sequence": self._owned_sequence,
            "external_sequence": self._external_sequence,
            "restore_verification": self._restore_verification,
            "operations": list(self._events),
            "content_values_persisted": False,
        }
        path.write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def close_without_restore(self) -> None:
        """Close without clipboard access before writes or after losing ownership."""
        if self._ready and not self._restored and not self._ownership_lost:
            raise ClipboardSafetyError("refusing to close clipboard broker before verified restore")
        if self._backend is not None:
            if not self._backend_closed:
                self._backend.close()
                self._backend_closed = True
            return
        process = self.process
        if process is None:
            return
        try:
            if process.poll() is None:
                if process.stdin is not None:
                    process.stdin.write('{"op":"quit"}\n')
                    process.stdin.flush()
                    process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        finally:
            if self._response_reader is not None:
                self._response_reader.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def close(self) -> None:
        if self._ready and not self._restored and not self._ownership_lost:
            self.restore()
        self.save_evidence()
        self.close_without_restore()

    def __enter__(self) -> "ClipboardBroker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        restore_error: BaseException | None = None
        try:
            if self._ready and not self._restored and not self._ownership_lost:
                self.restore()
        except BaseException as error:
            restore_error = error
        try:
            # Save status even on failure; never save any clipboard value.
            self.save_evidence()
        finally:
            if self._restored or not self._ready or self._ownership_lost:
                self.close_without_restore()
            elif self.process is not None and self.process.poll() is None:
                # The single restore attempt failed without proving external
                # ownership loss. Never claim a clean shutdown or restoration;
                # close only this exact helper after recording the failure.
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
        if restore_error is not None:
            raise restore_error

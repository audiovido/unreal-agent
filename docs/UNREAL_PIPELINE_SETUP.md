# Unreal Vision Pipeline Setup Guide

## Overview
This document outlines the steps to restore and verify the native Unreal vision integration pipeline: capture → Qwen3-VL analysis → structured visual review.

## Current Status
- ✅ API server started successfully on port 8765
- ✅ C++ capture functionality confirmed functional  
- ✅ API server running on port 8765
- ✅ Qwen3-VL vision call tested successfully with real screenshot

## Pipeline Components
1. **Unreal Editor**: Required for socket communication at `127.0.0.1:6766`
2. **UnrealAgentBridge Plugin**: Handles communication between Python and Unreal
3. **C++ Capture Functionality**: Native viewport capture in Unreal
4. **Qwen3-VL Vision Analysis**: Visual quality assessment
5. **Structured Review System**: Processed feedback generation

## Required Setup Steps

### Step 1: Start Unreal Editor
```bash
# Navigate to your UE_5.8 installation directory
cd "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64"

# Launch Unreal Editor with the AudioVidoLivingCity project
UnrealEditor.exe "C:\Users\Shadow\Desktop\app\AudioVidoLivingCity\AudioVidoLivingCity.uproject"
```

### Step 2: Enable UnrealAgentBridge Plugin
- Open the project in Unreal Editor
- Go to Edit → Plugins
- Ensure "UnrealAgentBridge" plugin is enabled

### Step 3: Verify Bridge Connectivity
Once Unreal Editor is running with the bridge:
```bash
# Test connectivity
python test_capture.py
```

### Step 4: Run Full Pipeline
```bash
# Capture and analyze
python test_capture.py
```

## Expected Results
After completing all steps:

1. **Capture**: Native viewport screenshot captured to `Saved/UnrealAgent/viewport_latest.png`
2. **Analysis**: Qwen3-VL processes the image and returns structured JSON
3. **Review**: Structured visual review report generated

## Troubleshooting

### Bridge Not Responding
If you get "ConnectionRefusedError":
1. Verify Unreal Editor is running with the correct project
2. Confirm the UnrealAgentBridge plugin is enabled
3. Check that the bridge listens on `127.0.0.1:6766`

### Capture Issues
If capture fails:
1. Ensure Unreal Editor has focus and active viewport
2. Verify C++ blueprint functions are correctly implemented
3. Check file permissions for project Saved directory

## Files Involved
- `tools/unreal/unreal_bridge.py` - Bridge communication layer
- `test_capture.py` - Capture test script  
- `app/api.py` - API server implementation
- `UnrealAgentBlueprintLibrary.cpp/h` - C++ capture functions

## Next Steps
1. Launch Unreal Editor from UE_5.8 with AudioVidoLivingCity project
2. Confirm bridge connectivity at `127.0.0.1:6766`
3. Run `test_capture.py` to verify capture functionality
4. Execute full pipeline for end-to-end testing
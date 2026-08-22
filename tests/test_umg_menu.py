#!/usr/bin/env python3
"""
UMG Menu Test for Unreal Agent
This script will create a safe test Widget Blueprint with title, buttons and styling.
"""

import requests
import json

def test_umg_menu():
    """Create a UMG menu with proper structure."""
    
    print("=== STARTING UMG MENU CREATION ===")
    
    # First, let's check if the bridge is working
    try:
        response = requests.get("http://127.0.0.1:6766/ping")
        if not response.json().get('ok'):
            print("Bridge not available")
            return False
        print("Bridge is ready!")
    except Exception as e:
        print(f"Failed to connect to bridge: {e}")
        return False
    
    # Create a simple Blueprint for UMG menu
    blueprint_code = '''
// Simple UMG Menu Blueprint
class UMyMenuWidget : public UUserWidget
{
    GENERATED_BODY()

public:
    virtual void NativeConstruct() override;
    
    UPROPERTY(meta=(BindWidget))
    UTextBlock* TitleText;
    
    UPROPERTY(meta=(BindWidget))
    UButton* StartButton;
    
    UPROPERTY(meta=(BindWidget))
    UButton* SettingsButton;
    
    UPROPERTY(meta=(BindWidget))
    UButton* QuitButton;
};

void UMyMenuWidget::NativeConstruct()
{
    Super::NativeConstruct();
    
    // Set up button click events
    if (StartButton)
    {
        StartButton->OnClicked.AddDynamic(this, &UMyMenuWidget::OnStartClicked);
    }
    
    if (SettingsButton)
    {
        SettingsButton->OnClicked.AddDynamic(this, &UMyMenuWidget::OnSettingsClicked);
    }
    
    if (QuitButton)
    {
        QuitButton->OnClicked.AddDynamic(this, &UMyMenuWidget::OnQuitClicked);
    }
}

void UMyMenuWidget::OnStartClicked()
{
    // Start game logic
    UE_LOG(LogTemp, Log, TEXT("Start button clicked"));
}

void UMyMenuWidget::OnSettingsClicked()
{
    // Settings logic  
    UE_LOG(LogTemp, Log, TEXT("Settings button clicked"));
}

void UMyMenuWidget::OnQuitClicked()
{
    // Quit logic
    UE_LOG(LogTemp, Log, TEXT("Quit button clicked"));
}
'''
    
    # Save the blueprint code as a file
    try:
        with open('Saved/UnrealAgent/UMG_Menu_Blueprint.txt', 'w') as f:
            f.write(blueprint_code)
        
        print("Blueprint saved successfully!")
        
        # Create a widget in Unreal using the bridge
        response = requests.post("http://127.0.0.1:6766/create_actor", 
                               json={
                                   "actor_type": "WidgetComponent",
                                   "location": [0, 0, 0],
                                   "widget_class": "UMyMenuWidget"
                               })
        
        print(f"Widget creation result: {response.json()}")
        
        # Set up proper layout and styling
        response = requests.post("http://127.0.0.1:6766/set_actor_properties", 
                               json={
                                   "actor_name": "MyMenuWidget",
                                   "properties": {
                                       "bIsFocusable": True,
                                       "bCanEverTick": True,
                                       "ForegroundColor": [1, 1, 1, 1],
                                       "HorizontalAlignment": "HAlign_Center",
                                       "VerticalAlignment": "VAlign_Center"
                                   }
                               })
        
        print(f"Widget properties set: {response.json()}")
        
        # Capture viewport for visual review
        response = requests.post("http://127.0.0.1:6766/capture_viewport")
        print(f"Viewport capture result: {response.json()}")
        
        return True
        
    except Exception as e:
        print(f"Error creating UMG menu: {e}")
        return False

if __name__ == "__main__":
    try:
        success = test_umg_menu()
        if success:
            print("UMG Menu creation successful!")
        else:
            print("UMG Menu creation failed!")
    except Exception as e:
        print(f"Error during UMG menu creation: {e}")
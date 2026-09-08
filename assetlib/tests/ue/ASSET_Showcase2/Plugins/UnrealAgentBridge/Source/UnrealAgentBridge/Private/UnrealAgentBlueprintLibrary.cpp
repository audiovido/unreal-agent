#include "UnrealAgentBlueprintLibrary.h"

#include "Editor.h"
#include "LevelEditorViewport.h"
#include "UnrealClient.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "ImageUtils.h"
#include "ImageCore.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"

#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraph/EdGraphSchema.h"
#include "Engine/Blueprint.h"
#include "K2Node_CallFunction.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"

namespace UnrealAgentBridgeInternal
{
    static UBlueprint* LoadBlueprint(const FString& Path)
    {
        return LoadObject<UBlueprint>(nullptr, *Path);
    }

    static UEdGraph* FindGraph(UBlueprint* Blueprint, const FString& GraphName)
    {
        if (!Blueprint)
            return nullptr;

        TArray<UEdGraph*> Graphs;
        Blueprint->GetAllGraphs(Graphs);

        for (UEdGraph* Graph : Graphs)
        {
            if (Graph && Graph->GetName().Equals(GraphName, ESearchCase::IgnoreCase))
                return Graph;
        }

        return nullptr;
    }

    static UEdGraphNode* FindNodeByTitle(UEdGraph* Graph, const FString& WantedTitle)
    {
        if (!Graph)
            return nullptr;

        for (UEdGraphNode* Node : Graph->Nodes)
        {
            if (!Node)
                continue;

            const FString Title =
                Node->GetNodeTitle(ENodeTitleType::ListView).ToString();

            if (Title.Equals(WantedTitle, ESearchCase::IgnoreCase) ||
                Title.Contains(WantedTitle, ESearchCase::IgnoreCase))
            {
                return Node;
            }
        }

        return nullptr;
    }

    static UEdGraphPin* FindPin(UEdGraphNode* Node, const FName PinName)
    {
        if (!Node)
            return nullptr;

        for (UEdGraphPin* Pin : Node->Pins)
        {
            if (Pin && Pin->PinName == PinName)
                return Pin;
        }

        return nullptr;
    }
}

UK2Node_CallFunction* UUnrealAgentBlueprintLibrary::AddCallFunctionNode(
    const FString& BlueprintAssetPath,
    const FString& GraphName,
    const FString& FunctionClassPath,
    const FName FunctionName,
    int32 X,
    int32 Y)
{
    using namespace UnrealAgentBridgeInternal;

    UBlueprint* Blueprint = LoadBlueprint(BlueprintAssetPath);
    if (!Blueprint)
        return nullptr;

    UEdGraph* Graph = FindGraph(Blueprint, GraphName);
    if (!Graph)
        return nullptr;

    UClass* FunctionClass = LoadObject<UClass>(nullptr, *FunctionClassPath);
    if (!FunctionClass)
        return nullptr;

    UFunction* Function = FunctionClass->FindFunctionByName(FunctionName);
    if (!Function)
        return nullptr;

    Blueprint->Modify();
    Graph->Modify();

    UK2Node_CallFunction* Node =
        NewObject<UK2Node_CallFunction>(Graph);

    if (!Node)
        return nullptr;

    Node->SetFlags(RF_Transactional);

    Graph->AddNode(Node, true, false);

    Node->SetFromFunction(Function);
    Node->NodePosX = X;
    Node->NodePosY = Y;
    Node->AllocateDefaultPins();

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

    return Node;
}

bool UUnrealAgentBlueprintLibrary::ConnectPinsByTitle(
    const FString& BlueprintAssetPath,
    const FString& GraphName,
    const FString& FromNodeTitle,
    const FName FromPinName,
    const FString& ToNodeTitle,
    const FName ToPinName)
{
    using namespace UnrealAgentBridgeInternal;

    UBlueprint* Blueprint = LoadBlueprint(BlueprintAssetPath);
    UEdGraph* Graph = FindGraph(Blueprint, GraphName);

    if (!Blueprint || !Graph)
        return false;

    UEdGraphNode* FromNode = FindNodeByTitle(Graph, FromNodeTitle);
    UEdGraphNode* ToNode = FindNodeByTitle(Graph, ToNodeTitle);

    UEdGraphPin* FromPin = FindPin(FromNode, FromPinName);
    UEdGraphPin* ToPin = FindPin(ToNode, ToPinName);

    if (!FromPin || !ToPin)
        return false;

    const UEdGraphSchema* Schema = Graph->GetSchema();
    if (!Schema)
        return false;

    const bool Connected =
        Schema->TryCreateConnection(FromPin, ToPin);

    if (Connected)
        FBlueprintEditorUtils::MarkBlueprintAsModified(Blueprint);

    return Connected;
}

bool UUnrealAgentBlueprintLibrary::SetPinDefaultValueByTitle(
    const FString& BlueprintAssetPath,
    const FString& GraphName,
    const FString& NodeTitle,
    const FName PinName,
    const FString& Value)
{
    using namespace UnrealAgentBridgeInternal;

    UBlueprint* Blueprint = LoadBlueprint(BlueprintAssetPath);
    UEdGraph* Graph = FindGraph(Blueprint, GraphName);

    if (!Blueprint || !Graph)
        return false;

    UEdGraphNode* Node = FindNodeByTitle(Graph, NodeTitle);
    UEdGraphPin* Pin = FindPin(Node, PinName);

    if (!Node || !Pin)
        return false;

    Pin->Modify();
    Pin->DefaultValue = Value;

    Node->PinDefaultValueChanged(Pin);

    FBlueprintEditorUtils::MarkBlueprintAsModified(Blueprint);

    return true;
}

bool UUnrealAgentBlueprintLibrary::CompileAndSaveBlueprint(
    const FString& BlueprintAssetPath)
{
    using namespace UnrealAgentBridgeInternal;

    UBlueprint* Blueprint = LoadBlueprint(BlueprintAssetPath);

    if (!Blueprint)
        return false;

    FKismetEditorUtilities::CompileBlueprint(Blueprint);
    Blueprint->MarkPackageDirty();

    return true;
}
TArray<FString> UUnrealAgentBlueprintLibrary::ListNodePins(
    const FString& BlueprintAssetPath,
    const FString& GraphName,
    const FString& NodeTitle)
{
    using namespace UnrealAgentBridgeInternal;

    TArray<FString> Result;

    UBlueprint* Blueprint = LoadBlueprint(BlueprintAssetPath);
    UEdGraph* Graph = FindGraph(Blueprint, GraphName);

    if (!Blueprint || !Graph)
        return Result;

    UEdGraphNode* Node = FindNodeByTitle(Graph, NodeTitle);

    if (!Node)
        return Result;

    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (Pin)
        {
            Result.Add(Pin->PinName.ToString());
        }
    }

    return Result;
}
TArray<FString> UUnrealAgentBlueprintLibrary::ListGraphNodes(
    const FString& BlueprintAssetPath,
    const FString& GraphName)
{
    using namespace UnrealAgentBridgeInternal;

    TArray<FString> Result;

    UBlueprint* Blueprint = LoadBlueprint(BlueprintAssetPath);
    UEdGraph* Graph = FindGraph(Blueprint, GraphName);

    if (!Blueprint || !Graph)
        return Result;

    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (Node)
        {
            Result.Add(
                Node->GetNodeTitle(
                    ENodeTitleType::ListView
                ).ToString()
            );
        }
    }

    return Result;
}


bool UUnrealAgentBlueprintLibrary::DeleteNodeByTitle(
    const FString& BlueprintAssetPath,
    const FString& GraphName,
    const FString& NodeTitle)
{
    using namespace UnrealAgentBridgeInternal;

    UBlueprint* Blueprint = LoadBlueprint(BlueprintAssetPath);
    UEdGraph* Graph = FindGraph(Blueprint, GraphName);

    if (!Blueprint || !Graph)
        return false;

    UEdGraphNode* Node = FindNodeByTitle(Graph, NodeTitle);

    if (!Node)
        return false;

    Blueprint->Modify();
    Graph->Modify();
    Node->Modify();

    Node->BreakAllNodeLinks();
    Graph->RemoveNode(Node);

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);

    return true;
}

bool UUnrealAgentBlueprintLibrary::CaptureActiveViewport(
    const FString& OutputPath)
{
    return CaptureActiveViewportDetailed(OutputPath).StartsWith(TEXT("OK|"));
}

FString UUnrealAgentBlueprintLibrary::CaptureActiveViewportDetailed(
    const FString& OutputPath)
{
#if WITH_EDITOR
    if (!GEditor)
    {
        return TEXT("ERROR|GEditor=null");
    }

    struct FCaptureCandidate
    {
        FViewport* Viewport = nullptr;
        FString Label;
        int64 Score = 0;
        FIntPoint Size = FIntPoint::ZeroValue;
    };

    TArray<FCaptureCandidate> Candidates;
    TSet<FViewport*> Seen;

    auto AddCandidate = [&Candidates, &Seen](
        FViewport* InViewport,
        const FString& InLabel,
        int64 Bonus)
    {
        if (!InViewport || Seen.Contains(InViewport))
        {
            return;
        }

        Seen.Add(InViewport);

        FIntPoint Size = InViewport->GetRenderTargetTextureSizeXY();

        if (Size.X <= 0 || Size.Y <= 0)
        {
            Size = InViewport->GetSizeXY();
        }

        if (Size.X <= 0 || Size.Y <= 0)
        {
            return;
        }

        FCaptureCandidate Candidate;
        Candidate.Viewport = InViewport;
        Candidate.Label = InLabel;
        Candidate.Size = Size;
        Candidate.Score =
            Bonus +
            (static_cast<int64>(Size.X) * static_cast<int64>(Size.Y));

        Candidates.Add(MoveTemp(Candidate));
    };

    // PIE/game viewport must win over editor viewports.
    if (GEngine && GEngine->GameViewport && GEngine->GameViewport->Viewport)
    {
        AddCandidate(
            GEngine->GameViewport->Viewport,
            TEXT("GameViewport"),
            1000000000000000LL
        );
    }

    const TArray<FLevelEditorViewportClient*>& LevelClients =
        GEditor->GetLevelViewportClients();

    for (int32 Index = 0; Index < LevelClients.Num(); ++Index)
    {
        FLevelEditorViewportClient* Client = LevelClients[Index];

        if (!Client || !Client->Viewport)
        {
            continue;
        }

        int64 Bonus = 0;

        if (Client->IsPerspective())
        {
            Bonus += 1000000000000LL;
        }

        if (Client->IsVisible())
        {
            Bonus += 100000000000LL;
        }

        AddCandidate(
            Client->Viewport,
            FString::Printf(
                TEXT("LevelViewport[%d]|perspective=%d|visible=%d"),
                Index,
                Client->IsPerspective() ? 1 : 0,
                Client->IsVisible() ? 1 : 0
            ),
            Bonus
        );
    }

    AddCandidate(
        GEditor->GetActiveViewport(),
        TEXT("GEditorActiveViewport"),
        10000000000LL
    );

    Candidates.Sort(
        [](const FCaptureCandidate& A, const FCaptureCandidate& B)
        {
            return A.Score > B.Score;
        }
    );

    if (Candidates.Num() == 0)
    {
        return FString::Printf(
            TEXT("ERROR|no_valid_viewport|level_clients=%d"),
            LevelClients.Num()
        );
    }

    FString FinalPath = OutputPath;

    if (FinalPath.IsEmpty())
    {
        FinalPath = FPaths::Combine(
            FPaths::ProjectSavedDir(),
            TEXT("UnrealAgent"),
            TEXT("viewport_latest.png")
        );
    }

    if (FPaths::GetExtension(FinalPath).IsEmpty())
    {
        FinalPath += TEXT(".png");
    }

    const FString OutputDirectory = FPaths::GetPath(FinalPath);

    if (!OutputDirectory.IsEmpty())
    {
        IFileManager::Get().MakeDirectory(
            *OutputDirectory,
            true
        );
    }

    FString LastFailure = TEXT("none");

    for (const FCaptureCandidate& Candidate : Candidates)
    {
        if (!Candidate.Viewport)
        {
            continue;
        }

        TArray<FColor> Pixels;

        FReadSurfaceDataFlags ReadFlags(RCM_UNorm);
        ReadFlags.SetLinearToGamma(true);

        const FIntRect SourceRect(
            0,
            0,
            Candidate.Size.X,
            Candidate.Size.Y
        );

        const bool bRead = Candidate.Viewport->ReadPixels(
            Pixels,
            ReadFlags,
            SourceRect
        );

        if (!bRead)
        {
            LastFailure = FString::Printf(
                TEXT("readpixels_failed|source=%s|width=%d|height=%d"),
                *Candidate.Label,
                Candidate.Size.X,
                Candidate.Size.Y
            );
            continue;
        }

        if (Pixels.Num() != Candidate.Size.X * Candidate.Size.Y)
        {
            LastFailure = FString::Printf(
                TEXT("pixel_count_mismatch|source=%s|got=%d|expected=%d"),
                *Candidate.Label,
                Pixels.Num(),
                Candidate.Size.X * Candidate.Size.Y
            );
            continue;
        }

        for (FColor& Pixel : Pixels)
        {
            Pixel.A = 255;
        }

        const FImageView ImageView(
            Pixels.GetData(),
            Candidate.Size.X,
            Candidate.Size.Y,
            EGammaSpace::sRGB
        );

        const bool bSaved = FImageUtils::SaveImageByExtension(
            *FinalPath,
            ImageView,
            100
        );

        if (!bSaved)
        {
            LastFailure = FString::Printf(
                TEXT("save_failed|source=%s|path=%s"),
                *Candidate.Label,
                *FinalPath
            );
            continue;
        }

        const int64 FileSize = IFileManager::Get().FileSize(*FinalPath);

        if (FileSize <= 0)
        {
            LastFailure = FString::Printf(
                TEXT("file_empty|source=%s|path=%s"),
                *Candidate.Label,
                *FinalPath
            );
            continue;
        }

        return FString::Printf(
            TEXT("OK|source=%s|width=%d|height=%d|bytes=%lld|path=%s"),
            *Candidate.Label,
            Candidate.Size.X,
            Candidate.Size.Y,
            static_cast<long long>(FileSize),
            *FinalPath
        );
    }

    return FString::Printf(
        TEXT("ERROR|candidates=%d|last=%s"),
        Candidates.Num(),
        *LastFailure
    );
#else
    return TEXT("ERROR|not_editor");
#endif
}

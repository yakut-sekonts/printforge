import React, { useEffect, useMemo, useState } from "react";
import type {
  ClearanceCalibrationArgs, ConstrainedSketch, ConstrainedSketchExtrudeArgs, DocState, DraftPrismArgs,
  EdgeFeatureKind, GeoError, TemplateDef, EdgeRef, FaceDomeArgs,
  FaceFeatureArgs, FaceFeatureProfile, FaceProfileKind, FitClearanceMode, FitFixtureId,
  FitPocketArgs, ImageReliefPreview, ImageReliefSettings, LoftArgs, PrintCheck,
  ImportResult, Operation, RevolveArgs, RibArgs,
  SheetBendArgs, ShellArgs, SketchExtrudeArgs, SketchProfile, SplitConnectorPairArgs, SweepArgs,
  SketchSolveResult, TextReliefArgs, ThreadPairArgs, VectorExtrudeArgs,
} from "./types";
import {
  faceDomeArgs as buildFaceDomeArgs, faceFeatureArgs as buildFaceFeatureArgs,
  sheetBendArgs as buildSheetBendArgs,
} from "./faceEditing";
import type {
  FaceDomePreview, FaceEditTarget, FaceFeaturePreview, FaceFeatureTarget, SheetBendPreview,
} from "./faceEditing";
import { evalExpression } from "./expr";

export interface EdgeToolUi {
  active: boolean;
  kind: EdgeFeatureKind;
  selected: EdgeRef | null;
  partId: string | null;
  size: string;
}

export interface PushPullUi {
  target: FaceEditTarget | null;
  value: string;
  dragging: boolean;
  reason: string | null;
}

interface Props {
  doc: DocState | null;
  templates: TemplateDef[];
  selectedFace: number | null;
  faceArea: number | null;
  pushPull: PushPullUi;
  faceFeatureTarget: FaceFeatureTarget | null;
  sheetBendTarget: FaceFeatureTarget | null;
  faceFeatureReason: string | null;
  onFaceFeaturePreview: (preview: FaceFeaturePreview | null) => void;
  onApplyFaceFeature: (args: FaceFeatureArgs) => void;
  onFaceDomePreview: (preview: FaceDomePreview | null) => void;
  onApplyFaceDome: (args: FaceDomeArgs) => void;
  onSheetBendPreview: (preview: SheetBendPreview | null) => void;
  onApplySheetBend: (args: SheetBendArgs) => void;
  onPushPullValue: (value: string) => void;
  onApplyPushPull: () => void;
  onCancelPushPull: () => void;
  selectedPartId: string | null;
  onApplyField: (name: string, raw: string, partId?: string) => void;
  // операции над деталями
  onAddPart: (t: TemplateDef) => void;
  onBoolean: (kind: "union" | "subtract" | "intersect", keepTool: boolean) => void;
  onArray: (count: number, step: [number, number, number]) => void;
  onMirror: (plane: "XY" | "XZ" | "YZ") => void;
  onSplit: (plane: "XY" | "XZ" | "YZ", offset: number) => void;
  onTransform: (translate: [number, number, number]) => void;
  onProfileExtrude: (args: {
    mode: "add" | "cut";
    plane: "XY" | "XZ" | "YZ";
    profile: Record<string, unknown>;
    depth?: number | "through";
    target_id?: string;
  }) => void;
  onSketchExtrude: (args: SketchExtrudeArgs) => void;
  constraintSolution: SketchSolveResult | null;
  onSketchSolve: (sketch: ConstrainedSketch) => void;
  onConstrainedSketchExtrude: (args: ConstrainedSketchExtrudeArgs) => void;
  onRevolve: (args: RevolveArgs) => void;
  onSweep: (args: SweepArgs) => void;
  onLoft: (args: LoftArgs) => void;
  onShell: (args: ShellArgs) => void;
  onDraftPrism: (args: DraftPrismArgs) => void;
  onRib: (args: RibArgs) => void;
  onFitPocket: (args: FitPocketArgs) => void;
  onVectorExtrude: (args: VectorExtrudeArgs) => void;
  onTextRelief: (args: TextReliefArgs) => void;
  onThreadPair: (args: ThreadPairArgs) => void;
  onClearanceCalibration: (args: ClearanceCalibrationArgs) => void;
  onSplitConnectorPair: (args: SplitConnectorPairArgs) => void;
  onArrayCircular: (count: number, angle: number, center: [number, number, number]) => void;
  onAlign: (axis: "x" | "y" | "z", align: "center" | "min" | "max", value: number) => void;
  measureResult: {
    source?: string; bbox?: number[]; volume?: number;
    faceDiameter?: number; faceError?: string; distance?: number;
  } | null;
  measureBusy: boolean;
  onMeasure: () => void;
  onMeasureFace: () => void;
  onMeasureDistance: (p0: [number, number, number], p1: [number, number, number]) => void;
  // обработка рёбер
  edgeTool: EdgeToolUi;
  onStartEdgeTool: (kind: EdgeFeatureKind) => void;
  onSelectEdge: (e: EdgeRef) => void;
  onEdgeToolKind: (kind: EdgeFeatureKind) => void;
  onEdgeToolSize: (value: string) => void;
  onApplyEdgeTool: () => void;
  onCancelEdgeTool: () => void;
  onClearError: () => void;
  // проверка печати
  printChecks: PrintCheck[] | null;
  printBusy: boolean;
  onPrintCheck: (printer: { x: number; y: number; z: number }) => void;
  // импорт
  importPreview: ImportResult | null;
  importBusy: boolean;
  onImport: (path: string, format: "step" | "stl", unitScale?: number) => void;
  onApplyMeshImport: (path: string, unitScale: number) => void;
  onCancelImportPreview: () => void;
  onMeshTransform: (translate: [number, number, number], scale: number) => void;
  onMeshRepair: () => void;
  onMeshDecimate: (targetRatio: number) => void;
  imageReliefPreview: ImageReliefPreview | null;
  onImageReliefPreview: (settings: ImageReliefSettings) => void;
  onImageReliefApply: (settings: ImageReliefSettings, expectedSha256: string) => void;
  onCancelImageReliefPreview: () => void;
  // файлы
  savePath: string; setSavePath: (v: string) => void;
  openPath: string; setOpenPath: (v: string) => void;
  exportPath: string; setExportPath: (v: string) => void;
  onSave: () => void; onOpen: () => void;
  onExport: (format: "stl" | "step" | "3mf") => void;
}

const PRINTER_KEY = "pf-printer";

function InspectorSection({ title, children, reveal = false, className = "" }: {
  title: string;
  children: React.ReactNode;
  reveal?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(reveal);

  useEffect(() => {
    if (reveal) setOpen(true);
  }, [reveal]);

  return (
    <details
      className={`inspector-section ${className}`}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>{title}</summary>
      <div className="inspector-section-content">{children}</div>
    </details>
  );
}

function loadPrinter(): { x: string; y: string; z: string } {
  try {
    const raw = localStorage.getItem(PRINTER_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* игнор */ }
  return { x: "220", y: "220", z: "250" };
}

function fmtNum(v: number): string {
  return String(Math.round(v * 100) / 100);
}

function rectangleProfile(width: number, height: number, holeDiameter = 0): SketchProfile {
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  return {
    regions: [{
      outer: {
        kind: "polygon",
        points: [
          [-halfWidth, -halfHeight], [halfWidth, -halfHeight],
          [halfWidth, halfHeight], [-halfWidth, halfHeight],
        ],
      },
      holes: holeDiameter > 0
        ? [{ kind: "circle", center: [0, 0], radius: holeDiameter / 2 }]
        : [],
    }],
  };
}

function constrainedRectangleSketch(width: number, height: number): ConstrainedSketch {
  const order = ["bottom", "right", "top", "left"];
  return {
    entities: [
      { id: "bottom", type: "line", start: [0.1, -0.2], end: [width - 0.2, 0.3] },
      { id: "right", type: "line", start: [width + 0.2, 0.1], end: [width - 0.3, height - 0.2] },
      { id: "top", type: "line", start: [width + 0.1, height + 0.2], end: [-0.2, height - 0.3] },
      { id: "left", type: "line", start: [0.2, height + 0.1], end: [-0.1, 0.2] },
    ],
    constraints: [
      ...order.map((entityId, index) => ({
        type: "coincident" as const,
        a: [entityId, "end"] as [string, "end"],
        b: [order[(index + 1) % order.length], "start"] as [string, "start"],
      })),
      { type: "horizontal", entity: "bottom" },
      { type: "horizontal", entity: "top" },
      { type: "vertical", entity: "right" },
      { type: "vertical", entity: "left" },
      { type: "dimension", kind: "distance_x", a: ["bottom", "start"], b: ["bottom", "end"], value: width },
      { type: "dimension", kind: "distance_y", a: ["right", "start"], b: ["right", "end"], value: height },
      { type: "fix", point: ["bottom", "start"], value: [0, 0] },
    ],
    regions: [{ outer: order, holes: [] }],
  };
}

function circleProfile(radius: number): SketchProfile {
  return { regions: [{ outer: { kind: "circle", center: [0, 0], radius }, holes: [] }] };
}

function sameEdge(a: EdgeRef, b: EdgeRef): boolean {
  return a.kind === b.kind && a.solid_index === b.solid_index &&
    a.midpoint.every((v, i) => Math.abs(v - b.midpoint[i]) < 1e-6);
}

function isFaceFeatureProfile(
  profile: FaceFeatureProfile | SketchProfile | undefined,
): profile is FaceFeatureProfile {
  return !!profile && "kind" in profile &&
    ["rectangle", "circle", "ring", "slot"].includes(profile.kind);
}

function isSupportedFlatBendCut(operation: Operation, targetId: string | undefined): boolean {
  return operation.op === "face_feature" && operation.target_id === targetId &&
    operation.mode === "cut" && operation.depth === "through" &&
    operation.face_ref?.kind === "outer_planar" && operation.face_ref.axis === "z" &&
    operation.face_ref.side === 1 && isFaceFeatureProfile(operation.profile);
}

function flatCutBendSpan(
  operation: Operation,
  bendAxis: "x" | "y",
): { center: number; extent: number } | null {
  const profile = operation.profile;
  const anchor = operation.face_ref?.kind === "outer_planar" ? operation.face_ref.anchor : null;
  if (!isFaceFeatureProfile(profile) || !anchor) return null;
  const axisIndex = bendAxis === "x" ? 0 : 1;
  const center = Number(anchor[axisIndex]) + Number(profile.center?.[axisIndex]);
  let extent: number;
  if (profile.kind === "rectangle") {
    extent = Number(bendAxis === "x" ? profile.width : profile.height) / 2;
  } else if (profile.kind === "circle") {
    extent = Number(profile.diameter) / 2;
  } else if (profile.kind === "ring") {
    extent = Number(profile.outer_diameter) / 2;
  } else if (profile.kind === "slot") {
    extent = Number(bendAxis === "x" ? profile.length : profile.width) / 2;
  } else {
    return null;
  }
  return Number.isFinite(center) && Number.isFinite(extent) && extent > 0
    ? { center, extent }
    : null;
}

export function ParamsPanel(props: Props) {
  const { doc, templates, selectedPartId } = props;
  // активная деталь: выбранная или первая
  const activePart = selectedPartId
    ? doc?.parts?.find((part) => part.part_id === selectedPartId) ?? null
    : doc?.parts?.[0] ?? null;
  const isFirstPart = !activePart || doc?.parts?.[0]?.part_id === activePart.part_id;
  const template = templates.find((candidate) => candidate.template_id ===
    (selectedPartId ? activePart?.template : activePart?.template ?? doc?.template)) ?? null;
  const paramSource: Record<string, number> = activePart?.params ?? doc?.params ?? {};
  const exprFor = (name: string, def: number): string => {
    if (isFirstPart && doc?.expressions?.[name]) return doc.expressions[name];
    const v = paramSource[name];
    return v != null ? String(v) : String(def);
  };
  const [values, setValues] = useState<Record<string, string>>({});
  const [exprError, setExprError] = useState<string | null>(null);
  const [multiHint, setMultiHint] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [printer, setPrinter] = useState(loadPrinter);
  const [importPath, setImportPath] = useState("~/model.step");
  const [importFormat, setImportFormat] = useState<"step" | "stl">("step");
  const [meshTranslate, setMeshTranslate] = useState({ x: "0", y: "0", z: "0" });
  const [meshScale, setMeshScale] = useState("1");
  const [meshTargetRatio, setMeshTargetRatio] = useState("0.5");
  const [imagePath, setImagePath] = useState("~/relief.png");
  const [imageWidth, setImageWidth] = useState("50");
  const [imageReliefHeight, setImageReliefHeight] = useState("3");
  const [imageBaseThickness, setImageBaseThickness] = useState("1.5");
  const [imageSamples, setImageSamples] = useState("96");
  const [imageSeed, setImageSeed] = useState("0");
  const [imageNoise, setImageNoise] = useState("0.015");
  const [imageInvert, setImageInvert] = useState(false);
  const [keepTool, setKeepTool] = useState(false);
  const [arrayCount, setArrayCount] = useState("2");
  const [arrayStep, setArrayStep] = useState({ x: "50", y: "0", z: "0" });
  const [mirrorPlane, setMirrorPlane] = useState<"XY" | "XZ" | "YZ">("YZ");
  const [splitPlane, setSplitPlane] = useState<"XY" | "XZ" | "YZ">("XY");
  const [splitOffset, setSplitOffset] = useState("0");
  const [extendedTool, setExtendedTool] = useState<
    "sketch" | "constraints" | "revolve" | "sweep" | "loft" | "shell" | "draft" | "rib" | "fit" |
    "vector" | "text" | "thread" | "calibration" | "connector"
  >("sketch");
  const [extendedValues, setExtendedValues] = useState({
    width: "40", height: "20", depth: "5", hole: "10",
    innerRadius: "5", outerRadius: "10", angle: "360",
    pathLength: "20", sectionRadius: "2", loftRadius1: "10",
    loftRadius2: "5", loftHeight: "20",
    shellOuterRadius: "10", shellHeight: "20", shellWall: "2", shellBottom: "3",
    draftWidth: "20", draftDepth: "12", draftHeight: "10", draftAngle: "5",
    baseLength: "40", baseWidth: "20", baseThickness: "4", ribLength: "15",
    ribHeight: "12", ribWidth: "3", ribOverlap: "1",
    fitFixture: "bearing_608", fitBodyLength: "32", fitBodyWidth: "32",
    fitBodyHeight: "12", fitClearance: "0.2", fitClearanceMode: "diametral",
    vectorPath: "~/profile.svg", vectorFormat: "svg", vectorHeight: "5", vectorUnitScale: "1",
    textValue: "О", textFontSize: "10", textReliefHeight: "1", textBodyLength: "30",
    textBodyWidth: "20", textBodyHeight: "4", textMode: "add",
    threadDiameter: "10", threadPitch: "1.5", threadLength: "12", threadHand: "right",
    threadClearance: "0.3", threadNutHeight: "5", threadNutAcrossFlats: "18",
    calibrationValues: "0.10, 0.20, 0.35", calibrationNominal: "8",
    calibrationLength: "24", calibrationWidth: "18", calibrationThickness: "3",
    calibrationSpacing: "28", calibrationFontSize: "3", calibrationLabelHeight: "0.6",
    calibrationProfile: "PLA test v1",
    connectorLength: "40", connectorWidth: "24", connectorHeight: "10",
    connectorPinRadius: "2", connectorPinLength: "6", connectorClearance: "0.25",
    connectorSeparation: "5",
  });
  const [translate, setTranslate] = useState({ x: "0", y: "0", z: "0" });
  const [profileKind, setProfileKind] = useState<"rectangle" | "circle" | "ring" | "slot">("rectangle");
  const [profileDims, setProfileDims] = useState({ width: "20", height: "10", diameter: "10", outer_diameter: "20", inner_diameter: "10", slot_width: "6", slot_length: "20" });
  const [profileCenter, setProfileCenter] = useState({ x: "0", y: "0" });
  const [profilePlane, setProfilePlane] = useState<"XY" | "XZ" | "YZ">("XY");
  const [profileMode, setProfileMode] = useState<"add" | "cut">("add");
  const [profileDepth, setProfileDepth] = useState("5");
  const [profileThrough, setProfileThrough] = useState(true);
  const [faceFeatureOpen, setFaceFeatureOpen] = useState(false);
  const [faceFeatureMode, setFaceFeatureMode] = useState<"add" | "cut">("cut");
  const [faceFeatureKind, setFaceFeatureKind] = useState<FaceProfileKind>("circle");
  const [faceFeatureDims, setFaceFeatureDims] = useState({
    width: "10", height: "8", diameter: "8", outer_diameter: "12",
    inner_diameter: "6", length: "20",
  });
  const [faceFeatureCenter, setFaceFeatureCenter] = useState({ u: "0", v: "0" });
  const [faceFeatureDepth, setFaceFeatureDepth] = useState("4");
  const [faceFeatureThrough, setFaceFeatureThrough] = useState(true);
  const [faceDomeOpen, setFaceDomeOpen] = useState(false);
  const [faceDomeMode, setFaceDomeMode] = useState<"add" | "cut">("add");
  const [faceDomeDiameter, setFaceDomeDiameter] = useState("20");
  const [faceDomeHeight, setFaceDomeHeight] = useState("4");
  const [faceDomeCenter, setFaceDomeCenter] = useState({ u: "0", v: "0" });
  const [sheetBendOpen, setSheetBendOpen] = useState(false);
  const [sheetBendAxis, setSheetBendAxis] = useState<"x" | "y">("x");
  const [sheetBendPosition, setSheetBendPosition] = useState("0");
  const [sheetBendAngle, setSheetBendAngle] = useState("90");
  const [sheetBendRadius, setSheetBendRadius] = useState("5");
  const [sheetBendMovingSide, setSheetBendMovingSide] = useState<-1 | 1>(1);
  const [sheetBendDirection, setSheetBendDirection] = useState<-1 | 1>(1);
  const [circCount, setCircCount] = useState("4");
  const [circAngle, setCircAngle] = useState("360");
  const [circCenter, setCircCenter] = useState({ x: "0", y: "0", z: "0" });
  const [alignAxis, setAlignAxis] = useState<"x" | "y" | "z">("z");
  const [alignMode, setAlignMode] = useState<"center" | "min" | "max">("min");
  const [alignValue, setAlignValue] = useState("0");
  const [distP0, setDistP0] = useState({ x: "0", y: "0", z: "0" });
  const [distP1, setDistP1] = useState({ x: "0", y: "0", z: "0" });

  // значения полей из активной детали
  useEffect(() => {
    if (!doc || !template) return;
    const next: Record<string, string> = {};
    for (const p of template.params) next[p.name] = exprFor(p.name, p.default);
    setValues(next);
    setMultiHint(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, template, selectedPartId]);

  useEffect(() => {
    setFaceFeatureOpen(false);
    setFaceDomeOpen(false);
    setSheetBendOpen(false);
    if (props.sheetBendTarget?.axis === "x") setSheetBendAxis("y");
    if (props.sheetBendTarget?.axis === "y") setSheetBendAxis("x");
    props.onFaceFeaturePreview(null);
    props.onFaceDomePreview(null);
    props.onSheetBendPreview(null);
  }, [props.selectedFace, props.sheetBendTarget, props.onFaceFeaturePreview, props.onFaceDomePreview,
    props.onSheetBendPreview]);

  const changedFields = useMemo(() => {
    if (!doc || !template) return [];
    return template.params.filter((p) => {
      const cur = exprFor(p.name, p.default);
      return (values[p.name] ?? cur).trim() !== cur;
    }).map((p) => p.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, doc, template]);

  const applyOne = (name: string, raw: string) => {
    const vars: Record<string, number> = { ...paramSource };
    try {
      const v = evalExpression(raw.trim(), vars);
      if (v <= 0) { setExprError(`Значение должно быть больше нуля`); return; }
      setExprError(null);
      setMultiHint(false);
      props.onApplyField(name, raw.trim(), activePart?.part_id);
    } catch (e) {
      setExprError(e instanceof Error ? e.message : String(e));
    }
  };

  const applyButton = () => {
    if (changedFields.length === 1) {
      applyOne(changedFields[0], values[changedFields[0]]);
    } else if (changedFields.length > 1) {
      setMultiHint(true);
    }
  };

  const computedHint = (name: string): string | null => {
    const raw = (values[name] ?? "").trim();
    if (!raw || /^-?\d+([.,]\d+)?$/.test(raw)) return null;
    try {
      const v = evalExpression(raw, { ...paramSource });
      return `= ${fmtNum(v)} мм`;
    } catch {
      return "ошибка в выражении";
    }
  };

  const liveParts = doc?.stats?.parts ?? [];
  const targetPart = liveParts.find((p) => p.part_id === selectedPartId) ?? liveParts[0] ?? null;
  const toolPart = targetPart
    ? liveParts[(liveParts.indexOf(targetPart) + 1) % liveParts.length] ?? null
    : null;
  const booleanReady = liveParts.length >= 2 && !!targetPart && !!toolPart;
  const num = (s: string) => Number(s.replace(",", ".")) || 0;
  const setExtendedValue = (name: keyof typeof extendedValues, value: string) => {
    setExtendedValues((current) => ({ ...current, [name]: value }));
  };
  const faceNumber = (value: string) => Number(value.replace(",", "."));

  const faceFeatureProfile = useMemo<FaceFeatureProfile>(() => {
    const profile: FaceFeatureProfile = {
      kind: faceFeatureKind,
      center: [faceNumber(faceFeatureCenter.u), faceNumber(faceFeatureCenter.v)],
    };
    if (faceFeatureKind === "rectangle") {
      profile.width = faceNumber(faceFeatureDims.width);
      profile.height = faceNumber(faceFeatureDims.height);
    } else if (faceFeatureKind === "circle") {
      profile.diameter = faceNumber(faceFeatureDims.diameter);
    } else if (faceFeatureKind === "ring") {
      profile.outer_diameter = faceNumber(faceFeatureDims.outer_diameter);
      profile.inner_diameter = faceNumber(faceFeatureDims.inner_diameter);
    } else {
      profile.width = faceNumber(faceFeatureDims.width);
      profile.length = faceNumber(faceFeatureDims.length);
    }
    return profile;
  }, [faceFeatureKind, faceFeatureDims, faceFeatureCenter]);

  const faceFeatureError = useMemo(() => {
    if (!props.faceFeatureTarget) return "Выберите поддерживаемую внешнюю плоскую грань.";
    if (!faceFeatureProfile.center.every(Number.isFinite)) return "Смещения U и V должны быть числами.";
    const positive = (value: number | undefined) => value != null && Number.isFinite(value) && value > 0;
    if (faceFeatureProfile.kind === "rectangle" &&
        (!positive(faceFeatureProfile.width) || !positive(faceFeatureProfile.height))) {
      return "Ширина и высота профиля должны быть больше нуля.";
    }
    if (faceFeatureProfile.kind === "circle" && !positive(faceFeatureProfile.diameter)) {
      return "Диаметр должен быть больше нуля.";
    }
    if (faceFeatureProfile.kind === "ring" &&
        (!positive(faceFeatureProfile.outer_diameter) || !positive(faceFeatureProfile.inner_diameter) ||
         faceFeatureProfile.inner_diameter! >= faceFeatureProfile.outer_diameter!)) {
      return "Внутренний диаметр должен быть меньше наружного.";
    }
    if (faceFeatureProfile.kind === "slot" &&
        (!positive(faceFeatureProfile.width) || !positive(faceFeatureProfile.length) ||
         faceFeatureProfile.length! <= faceFeatureProfile.width!)) {
      return "Длина паза должна быть больше его ширины.";
    }
    const depth = faceNumber(faceFeatureDepth);
    if (!(faceFeatureMode === "cut" && faceFeatureThrough) && (!Number.isFinite(depth) || depth <= 0)) {
      return "Глубина должна быть больше нуля.";
    }
    if (faceFeatureMode === "cut" && !faceFeatureThrough &&
        depth >= props.faceFeatureTarget.axisSpan - 0.01) {
      return "Для такой глубины выберите сквозной вырез.";
    }
    return null;
  }, [props.faceFeatureTarget, faceFeatureProfile, faceFeatureDepth, faceFeatureMode, faceFeatureThrough]);

  const faceFeatureRequest = useMemo<FaceFeatureArgs | null>(() => {
    if (!props.faceFeatureTarget || faceFeatureError) return null;
    const depth = faceFeatureMode === "cut" && faceFeatureThrough
      ? "through"
      : faceNumber(faceFeatureDepth);
    return buildFaceFeatureArgs(props.faceFeatureTarget, faceFeatureMode, faceFeatureProfile, depth);
  }, [props.faceFeatureTarget, faceFeatureError, faceFeatureMode, faceFeatureThrough,
    faceFeatureDepth, faceFeatureProfile]);

  useEffect(() => {
    props.onFaceFeaturePreview(
      faceFeatureOpen && faceFeatureRequest
        ? { target: props.faceFeatureTarget!, args: faceFeatureRequest }
        : null,
    );
    return () => props.onFaceFeaturePreview(null);
  }, [faceFeatureOpen, faceFeatureRequest, props.faceFeatureTarget, props.onFaceFeaturePreview]);

  const faceDomeError = useMemo(() => {
    if (!props.faceFeatureTarget) return "Выберите поддерживаемую внешнюю плоскую грань.";
    const center = [faceNumber(faceDomeCenter.u), faceNumber(faceDomeCenter.v)];
    const diameter = faceNumber(faceDomeDiameter);
    const height = faceNumber(faceDomeHeight);
    if (!center.every(Number.isFinite)) return "Смещения U и V должны быть числами.";
    if (!Number.isFinite(diameter) || diameter <= 0) return "Диаметр должен быть больше нуля.";
    if (!Number.isFinite(height) || height <= 0) return "Высота должна быть больше нуля.";
    if (height > diameter / 2) return "Высота не должна превышать половину диаметра.";
    if (faceDomeMode === "cut" && height >= props.faceFeatureTarget.axisSpan - 0.01) {
      return "Глубина вмятины достигает противоположной стороны.";
    }
    return null;
  }, [props.faceFeatureTarget, faceDomeCenter, faceDomeDiameter, faceDomeHeight, faceDomeMode]);

  const faceDomeRequest = useMemo<FaceDomeArgs | null>(() => {
    if (!props.faceFeatureTarget || faceDomeError) return null;
    return buildFaceDomeArgs(
      props.faceFeatureTarget,
      faceDomeMode,
      [faceNumber(faceDomeCenter.u), faceNumber(faceDomeCenter.v)],
      faceNumber(faceDomeDiameter),
      faceNumber(faceDomeHeight),
    );
  }, [props.faceFeatureTarget, faceDomeError, faceDomeMode, faceDomeCenter,
    faceDomeDiameter, faceDomeHeight]);

  useEffect(() => {
    props.onFaceDomePreview(
      faceDomeOpen && faceDomeRequest
        ? { target: props.faceFeatureTarget!, args: faceDomeRequest }
        : null,
    );
    return () => props.onFaceDomePreview(null);
  }, [faceDomeOpen, faceDomeRequest, props.faceFeatureTarget, props.onFaceDomePreview]);

  const sheetBendDimensions = useMemo(() => {
    const value = (name: string) => {
      const direct = activePart?.params[name];
      if (typeof direct === "number" && Number.isFinite(direct)) return direct;
      const fallback = template?.params.find((parameter) => parameter.name === name)?.default;
      return typeof fallback === "number" && Number.isFinite(fallback) ? fallback : 0;
    };
    return {
      length: value("length"),
      width: value("width"),
      thickness: value("height"),
      holeDiameter: value("hole_diameter"),
      holeOffset: value("hole_offset"),
    };
  }, [activePart, template]);

  const existingSheetBends = useMemo(() => (doc?.operations ?? [])
    .filter((operation) => operation.op === "sheet_bend" &&
      operation.target_id === activePart?.part_id)
    .map((operation) => operation as unknown as SheetBendArgs),
  [activePart?.part_id, doc?.operations]);

  const flatSheetCuts = useMemo(() => (doc?.operations ?? [])
    .filter((operation) => isSupportedFlatBendCut(operation, activePart?.part_id)),
  [activePart?.part_id, doc?.operations]);

  const perpendicularFlangeBend = props.sheetBendTarget?.axis === "x" ||
    props.sheetBendTarget?.axis === "y";

  const sheetBendStructuralReason = useMemo(() => {
    if (activePart?.template !== "plate_with_holes") return "Изгиб пока доступен только для пластины.";
    if (!props.sheetBendTarget) {
      return "Для изгиба выберите верхнюю грань пластины или внешнюю грань готового фланца.";
    }
    let bendStarted = false;
    for (const operation of doc?.operations ?? []) {
      if (operation.op === "face_feature" && !bendStarted &&
          isSupportedFlatBendCut(operation, activePart?.part_id)) {
        continue;
      }
      if (operation.op === "sheet_bend" && operation.target_id === activePart?.part_id) {
        bendStarted = true;
        continue;
      }
      return "Перед изгибом допустимы сквозные вырезы; затем изгибы должны идти подряд.";
    }
    if (perpendicularFlangeBend) {
      if (existingSheetBends.length !== 1) {
        return "Изгиб фланца должен следовать сразу после одного базового изгиба.";
      }
      const base = existingSheetBends[0];
      if (Math.abs(base.angle - 90) > 1e-7) {
        return "Изгиб фланца пока доступен только после базового изгиба 90°.";
      }
      if (base.bend_axis !== props.sheetBendTarget.axis ||
          base.moving_side !== props.sheetBendTarget.side) {
        return "Выберите внешнюю грань подвижного фланца базового изгиба.";
      }
      const baseLength = base.bend_axis === "x"
        ? sheetBendDimensions.length
        : sheetBendDimensions.width;
      const baseAllowance = (base.inside_radius + sheetBendDimensions.thickness / 2) *
        base.angle * Math.PI / 180;
      const targetBoundary = base.position +
        (base.moving_side < 0 ? -baseAllowance / 2 : baseAllowance / 2);
      for (const operation of flatSheetCuts) {
        const span = flatCutBendSpan(operation, base.bend_axis);
        if (!span) return "Параметры пользовательского выреза повреждены.";
        const featureMin = span.center - span.extent;
        const featureMax = span.center + span.extent;
        const onTargetFlange = base.moving_side < 0
          ? featureMax < targetBoundary - 1e-7
          : featureMin > targetBoundary + 1e-7;
        const touchesTargetFlange = base.moving_side < 0
          ? featureMin < targetBoundary + 1e-7
          : featureMax > targetBoundary - 1e-7;
        if (touchesTargetFlange && !onTargetFlange) {
          return "Пользовательский вырез должен целиком лежать на прямом участке выбранного фланца.";
        }
      }
      const flangeDepth = base.moving_side < 0
        ? base.position + baseLength / 2 - baseAllowance / 2
        : baseLength / 2 - base.position - baseAllowance / 2;
      if (flangeDepth <= 0.1) return "Фланец слишком короткий для второго изгиба.";
      return null;
    }
    if (existingSheetBends.some((operation) => operation.face_ref.axis !== "z")) {
      return "После изгиба фланца новые линии пока не поддерживаются.";
    }
    if (existingSheetBends.length >= 4) {
      return "Поддерживаются до четырёх последовательных линий изгиба.";
    }
    return null;
  }, [activePart, doc?.operations, existingSheetBends, props.sheetBendTarget,
    perpendicularFlangeBend, sheetBendDimensions, flatSheetCuts]);

  const sheetBendError = useMemo(() => {
    if (sheetBendStructuralReason) return sheetBendStructuralReason;
    const position = faceNumber(sheetBendPosition);
    const angle = faceNumber(sheetBendAngle);
    const radius = faceNumber(sheetBendRadius);
    if (![position, angle, radius].every(Number.isFinite)) return "Положение, угол и радиус должны быть числами.";
    if (angle < 5 || angle > 170) return "Угол должен быть от 5° до 170°.";
    if (radius <= 0) return "Внутренний радиус должен быть больше нуля.";
    const developedLength = sheetBendAxis === "x"
      ? sheetBendDimensions.length
      : sheetBendDimensions.width;
    const developedToBend = position + developedLength / 2;
    const bendAllowance = (radius + sheetBendDimensions.thickness / 2) * angle * Math.PI / 180;
    const zoneMin = developedToBend - bendAllowance / 2;
    const zoneMax = developedToBend + bendAllowance / 2;
    if (zoneMin <= 0.01 || zoneMax >= developedLength - 0.01) {
      return "Линия изгиба слишком близко к краю для этих угла и радиуса.";
    }
    if (sheetBendDimensions.holeDiameter > 0) {
      const holeRadius = sheetBendDimensions.holeDiameter / 2;
      const holeCoordinate = developedLength / 2 - sheetBendDimensions.holeOffset;
      for (const originalCoordinate of [-holeCoordinate, holeCoordinate]) {
        const developedHole = originalCoordinate + developedLength / 2;
        if (developedHole + holeRadius >= zoneMin && developedHole - holeRadius <= zoneMax) {
          return "Зона изгиба пересекает отверстие.";
        }
      }
    }
    for (const operation of perpendicularFlangeBend ? [] : flatSheetCuts) {
      const span = flatCutBendSpan(operation, sheetBendAxis);
      if (!span) return "Параметры пользовательского выреза повреждены.";
      if (!isFaceFeatureProfile(operation.profile)) {
        return "Параметры пользовательского выреза повреждены.";
      }
      const developedCut = span.center + developedLength / 2;
      if (developedCut + span.extent >= zoneMin && developedCut - span.extent <= zoneMax) {
        if (operation.profile?.kind !== "rectangle" && operation.profile?.kind !== "circle" &&
            operation.profile?.kind !== "ring" && operation.profile?.kind !== "slot") {
          return "Криволинейную bend-зону пока могут пересекать прямоугольный, круглый, кольцевой through-вырез или паз.";
        }
        if (operation.profile?.kind === "circle" || operation.profile?.kind === "ring" ||
            operation.profile?.kind === "slot") {
          const crossesExistingZone = existingSheetBends.some((existing) => {
            if (existing.bend_axis !== sheetBendAxis) return false;
            const existingCenter = existing.position + developedLength / 2;
            const existingAllowance = (existing.inside_radius + sheetBendDimensions.thickness / 2) *
              existing.angle * Math.PI / 180;
            const existingZoneMin = existingCenter - existingAllowance / 2;
            const existingZoneMax = existingCenter + existingAllowance / 2;
            return developedCut + span.extent >= existingZoneMin &&
              developedCut - span.extent <= existingZoneMax;
          });
          if (crossesExistingZone) {
            return "Круглый, кольцевой through-вырез или паз пока может пересекать только одну криволинейную bend-зону.";
          }
        }
      }
    }
    if (existingSheetBends.length > 0 && !perpendicularFlangeBend) {
      if (existingSheetBends.some((existing) => existing.bend_axis !== sheetBendAxis)) {
        return "Последовательные изгибы должны быть параллельны и использовать одну ось.";
      }
      for (const existing of existingSheetBends) {
        const existingCenter = existing.position + developedLength / 2;
        const existingAllowance = (existing.inside_radius + sheetBendDimensions.thickness / 2) *
          existing.angle * Math.PI / 180;
        const existingZoneMin = existingCenter - existingAllowance / 2;
        const existingZoneMax = existingCenter + existingAllowance / 2;
        if (zoneMin < existingZoneMax + 0.01 && zoneMax > existingZoneMin - 0.01) {
          return "Зоны последовательных изгибов пересекаются.";
        }
      }
      const ordered = [
        ...existingSheetBends.map((existing) => ({
          position: existing.position,
          movingSide: existing.moving_side,
        })),
        { position, movingSide: sheetBendMovingSide },
      ].sort((left, right) => left.position - right.position);
      let positiveSideStarted = false;
      for (const bend of ordered) {
        if (bend.movingSide > 0) positiveSideStarted = true;
        else if (positiveSideStarted) {
          return "Левая группа линий должна сгибать −ось, правая — +ось.";
        }
      }
    }
    return null;
  }, [sheetBendStructuralReason, sheetBendPosition, sheetBendAngle, sheetBendRadius,
    sheetBendAxis, sheetBendDimensions, sheetBendMovingSide, existingSheetBends, flatSheetCuts,
    perpendicularFlangeBend]);

  const sheetBendRequest = useMemo<SheetBendArgs | null>(() => {
    if (!props.sheetBendTarget || sheetBendError) return null;
    return buildSheetBendArgs(
      props.sheetBendTarget,
      sheetBendAxis,
      faceNumber(sheetBendPosition),
      faceNumber(sheetBendAngle),
      faceNumber(sheetBendRadius),
      sheetBendMovingSide,
      sheetBendDirection,
    );
  }, [props.sheetBendTarget, sheetBendError, sheetBendAxis, sheetBendPosition,
    sheetBendAngle, sheetBendRadius, sheetBendMovingSide, sheetBendDirection]);

  useEffect(() => {
    props.onSheetBendPreview(
      sheetBendOpen && sheetBendRequest
        ? {
            target: props.sheetBendTarget!,
            args: sheetBendRequest,
            bends: [...existingSheetBends, sheetBendRequest],
            length: sheetBendDimensions.length,
            width: sheetBendDimensions.width,
            thickness: sheetBendDimensions.thickness,
          }
        : null,
    );
    return () => props.onSheetBendPreview(null);
  }, [sheetBendOpen, sheetBendRequest, existingSheetBends, sheetBendDimensions, props.sheetBendTarget,
    props.onSheetBendPreview]);

  const err: GeoError | null = doc?.error ?? null;
  const isEdgeError = err?.code === "fillet_failed" || err?.code === "chamfer_failed" ||
    err?.code === "dome_failed" || err?.code === "bend_failed" || err?.code === "reselect_required" ||
    err?.code === "face_offset_failed" || err?.code === "split_failed" || err?.code === "unsupported_face" || err?.code === "bad_ref";
  const edges = doc?.stats?.edges ?? [];
  const edgeOperations = (doc?.operations ?? [])
    .filter((operation) => (operation.op === "fillet" || operation.op === "chamfer") && operation.edge_ref);

  const savePrinter = (p: { x: string; y: string; z: string }) => {
    setPrinter(p);
    localStorage.setItem(PRINTER_KEY, JSON.stringify(p));
  };

  const previewBbox = props.importPreview?.stats?.bbox;
  const previewExt = props.importPreview?.stats?.bbox_mesh;
  const calibrationValues = extendedValues.calibrationValues
    .split(",").map((value) => Number(value.trim()));
  const calibrationValuesValid = calibrationValues.length >= 2 && calibrationValues.length <= 10 &&
    calibrationValues.every((value) => Number.isFinite(value) && value >= 0) &&
    new Set(calibrationValues).size === calibrationValues.length;

  return (
    <aside className="right-panel" aria-label="Выбранная область и инструменты">
      <h2 className="panel-section">Инструменты модели</h2>
      <p className="inspector-intro">
        {doc?.stats?.is_valid
          ? "Выберите грань или ребро на сцене. Действия появятся рядом с моделью. Здесь — точные настройки и дополнительные инструменты."
          : "Начните с простой формы в центре сцены. Дополнительные способы создания и импорт доступны ниже."}
      </p>

      {err && (
        <div className="error-box" role="alert">
          <div className="error-title">Ошибка геометрии</div>
          <p>{err.message}</p>
          {err.detail && (
            <>
              <button className="link-btn" onClick={() => setDetailOpen(!detailOpen)}>
                {detailOpen ? "Скрыть подробности" : "Подробности"}
              </button>
              {detailOpen && <pre className="error-detail">{err.detail}</pre>}
            </>
          )}
          {isEdgeError ? (
            <button className="btn" data-cmd="error.close" aria-label="Закрыть ошибку" onClick={props.onClearError}>
              Закрыть
            </button>
          ) : (
            <button className="btn" data-cmd="op.undo" aria-label="Отменить изменение" onClick={props.onClearError}>
              Отменить изменение
            </button>
          )}
        </div>
      )}

      {doc && template ? (
        <InspectorSection title={`Размеры исходной формы — ${activePart?.name ?? template.title}`}>
        <div className="params-form">
          {template.params.map((p) => (
            <div className="param-field" key={p.name}>
              <label htmlFor={`param-${p.name}`}>{p.label}</label>
              <div className="param-input" data-cmd="parameter.set">
                <input
                  id={`param-${p.name}`}
                  inputMode="decimal"
                  value={values[p.name] ?? ""}
                  aria-label={`${p.label}, ${p.unit}`}
                  onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                  onKeyDown={(e) => { if (e.key === "Enter") applyOne(p.name, values[p.name] ?? ""); }}
                />
                <span className="param-unit">
                  {p.name === "gap" ? "мм, на одну сторону" : p.unit}
                </span>
              </div>
              {computedHint(p.name) && <div className="param-hint">{computedHint(p.name)}</div>}
            </div>
          ))}
          {exprError && <div className="error-inline" role="alert">{exprError}</div>}
          {multiHint && <div className="param-hint">Изменено несколько полей — применяйте каждое поле клавишей Enter.</div>}
          <button
            className="btn btn-primary"
            data-cmd="parameter.set"
            aria-label="Применить параметр"
            disabled={changedFields.length !== 1}
            onClick={applyButton}
          >
            Применить
          </button>
        </div>
        </InspectorSection>
      ) : null}

      <InspectorSection title="Другие способы создания" className="extended-tools">
        <p className="hint">Точные эскизные тела, траекторные операции, оболочка, уклон и ребро. Каждое применение добавляет одну операцию в историю.</p>
        <div className="op-row">
          <select value={extendedTool} aria-label="Расширенная операция" onChange={(event) => setExtendedTool(event.target.value as typeof extendedTool)}>
            <option value="sketch">Эскиз → выдавливание</option>
            <option value="constraints">Эскиз с ограничениями</option>
            <option value="revolve">Вращение профиля</option>
            <option value="sweep">Sweep по прямой</option>
            <option value="loft">Loft окружностей</option>
            <option value="shell">Цилиндрическая оболочка</option>
            <option value="draft">Призма с уклоном</option>
            <option value="rib">Ребро жёсткости</option>
            <option value="fit">Параметрическая посадка</option>
            <option value="vector">SVG / DXF → тело</option>
            <option value="text">Текстовый рельеф</option>
            <option value="thread">Резьбовая пара</option>
            <option value="calibration">Калибровка зазоров</option>
            <option value="connector">Разделение со штифтами</option>
          </select>
        </div>

        {extendedTool === "sketch" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.width} aria-label="Ширина эскиза, мм" onChange={(event) => setExtendedValue("width", event.target.value)} /><span className="param-unit">ширина, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.height} aria-label="Высота эскиза, мм" onChange={(event) => setExtendedValue("height", event.target.value)} /><span className="param-unit">высота, мм</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.depth} aria-label="Глубина эскиза, мм" onChange={(event) => setExtendedValue("depth", event.target.value)} /><span className="param-unit">глубина, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.hole} aria-label="Диаметр отверстия эскиза, мм" onChange={(event) => setExtendedValue("hole", event.target.value)} /><span className="param-unit">Ø отверстия, мм</span></div>
          </div>
          <button
            className="btn" data-cmd="op.sketch.extrude"
            disabled={num(extendedValues.width) <= 0 || num(extendedValues.height) <= 0 || num(extendedValues.depth) <= 0 || num(extendedValues.hole) < 0 || num(extendedValues.hole) >= Math.min(num(extendedValues.width), num(extendedValues.height))}
            onClick={() => props.onSketchExtrude({
              profile: rectangleProfile(num(extendedValues.width), num(extendedValues.height), num(extendedValues.hole)),
              plane: "XY", depth: num(extendedValues.depth), name: "Эскиз",
            })}
          >Создать по эскизу</button>
        </>}

        {extendedTool === "constraints" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.width} aria-label="Ширина ограниченного эскиза, мм" onChange={(event) => setExtendedValue("width", event.target.value)} /><span className="param-unit">ширина, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.height} aria-label="Высота ограниченного эскиза, мм" onChange={(event) => setExtendedValue("height", event.target.value)} /><span className="param-unit">высота, мм</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.depth} aria-label="Глубина ограниченного эскиза, мм" onChange={(event) => setExtendedValue("depth", event.target.value)} /><span className="param-unit">глубина, мм</span></div>
          </div>
          {props.constraintSolution && <div className="param-hint" role="status">
            {props.constraintSolution.status === "fully_constrained" ? "Полностью определён" : "Недоопределён"}; DOF: {props.constraintSolution.degrees_of_freedom}; max residual: {props.constraintSolution.max_residual.toExponential(2)}
            {props.constraintSolution.redundant_constraints > 0 ? `; совместимых избыточных: ${props.constraintSolution.redundant_constraints}` : ""}
          </div>}
          <div className="op-row">
            <button
              className="btn" data-cmd="op.sketch.solve"
              disabled={num(extendedValues.width) <= 0 || num(extendedValues.height) <= 0}
              onClick={() => props.onSketchSolve(constrainedRectangleSketch(num(extendedValues.width), num(extendedValues.height)))}
            >Проверить ограничения</button>
            <button
              className="btn btn-primary" data-cmd="op.sketch.constraint.apply"
              disabled={num(extendedValues.width) <= 0 || num(extendedValues.height) <= 0 || num(extendedValues.depth) <= 0}
              onClick={() => props.onConstrainedSketchExtrude({
                sketch: constrainedRectangleSketch(num(extendedValues.width), num(extendedValues.height)),
                plane: "XY", depth: num(extendedValues.depth), name: "Ограниченный эскиз",
              })}
            >Создать тело</button>
          </div>
        </>}

        {extendedTool === "revolve" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.innerRadius} aria-label="Внутренний радиус вращения, мм" onChange={(event) => setExtendedValue("innerRadius", event.target.value)} /><span className="param-unit">R внутр., мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.outerRadius} aria-label="Наружный радиус вращения, мм" onChange={(event) => setExtendedValue("outerRadius", event.target.value)} /><span className="param-unit">R наруж., мм</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.height} aria-label="Высота профиля вращения, мм" onChange={(event) => setExtendedValue("height", event.target.value)} /><span className="param-unit">высота, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.angle} aria-label="Угол вращения, градусы" onChange={(event) => setExtendedValue("angle", event.target.value)} /><span className="param-unit">угол, °</span></div>
          </div>
          <button
            className="btn" data-cmd="op.revolve"
            disabled={num(extendedValues.innerRadius) < 0 || num(extendedValues.outerRadius) <= num(extendedValues.innerRadius) || num(extendedValues.height) <= 0 || num(extendedValues.angle) <= 0 || num(extendedValues.angle) > 360}
            onClick={() => {
              const inner = num(extendedValues.innerRadius);
              const outer = num(extendedValues.outerRadius);
              const height = num(extendedValues.height);
              props.onRevolve({
                profile: { regions: [{ outer: { kind: "polygon", points: [[inner, 0], [outer, 0], [outer, height], [inner, height]] }, holes: [] }] },
                plane: "XZ", axis: { point: [0, 0, 0], direction: [0, 0, 1] },
                angle: num(extendedValues.angle), name: "Тело вращения",
              });
            }}
          >Создать вращением</button>
        </>}

        {extendedTool === "sweep" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.sectionRadius} aria-label="Радиус sweep, мм" onChange={(event) => setExtendedValue("sectionRadius", event.target.value)} /><span className="param-unit">радиус, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.pathLength} aria-label="Длина sweep, мм" onChange={(event) => setExtendedValue("pathLength", event.target.value)} /><span className="param-unit">длина, мм</span></div>
          </div>
          <button
            className="btn" data-cmd="op.sweep"
            disabled={num(extendedValues.sectionRadius) <= 0 || num(extendedValues.pathLength) <= 0}
            onClick={() => props.onSweep({
              section: { kind: "circle", radius: num(extendedValues.sectionRadius) },
              path: { points: [[0, 0, 0], [0, 0, num(extendedValues.pathLength)]] },
              name: "Sweep",
            })}
          >Создать sweep</button>
        </>}

        {extendedTool === "loft" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.loftRadius1} aria-label="Первый радиус loft, мм" onChange={(event) => setExtendedValue("loftRadius1", event.target.value)} /><span className="param-unit">R1, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.loftRadius2} aria-label="Второй радиус loft, мм" onChange={(event) => setExtendedValue("loftRadius2", event.target.value)} /><span className="param-unit">R2, мм</span></div>
          </div>
          <div className="op-row"><div className="param-input op-field"><input inputMode="decimal" value={extendedValues.loftHeight} aria-label="Высота loft, мм" onChange={(event) => setExtendedValue("loftHeight", event.target.value)} /><span className="param-unit">высота, мм</span></div></div>
          <button
            className="btn" data-cmd="op.loft"
            disabled={num(extendedValues.loftRadius1) <= 0 || num(extendedValues.loftRadius2) <= 0 || num(extendedValues.loftHeight) <= 0}
            onClick={() => props.onLoft({
              ruled: true,
              sections: [
                { plane: "XY", offset: 0, profile: circleProfile(num(extendedValues.loftRadius1)) },
                { plane: "XY", offset: num(extendedValues.loftHeight), profile: circleProfile(num(extendedValues.loftRadius2)) },
              ],
              name: "Loft",
            })}
          >Создать loft</button>
        </>}

        {extendedTool === "shell" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.shellOuterRadius} aria-label="Наружный радиус оболочки, мм" onChange={(event) => setExtendedValue("shellOuterRadius", event.target.value)} /><span className="param-unit">R наруж., мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.shellHeight} aria-label="Высота оболочки, мм" onChange={(event) => setExtendedValue("shellHeight", event.target.value)} /><span className="param-unit">высота, мм</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.shellWall} aria-label="Толщина стенки оболочки, мм" onChange={(event) => setExtendedValue("shellWall", event.target.value)} /><span className="param-unit">стенка, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.shellBottom} aria-label="Толщина дна оболочки, мм" onChange={(event) => setExtendedValue("shellBottom", event.target.value)} /><span className="param-unit">дно, мм</span></div>
          </div>
          <button
            className="btn" data-cmd="op.shell"
            disabled={num(extendedValues.shellOuterRadius) <= 0 || num(extendedValues.shellHeight) <= 0 || num(extendedValues.shellWall) <= 0 || num(extendedValues.shellWall) >= num(extendedValues.shellOuterRadius) || num(extendedValues.shellBottom) <= 0 || num(extendedValues.shellBottom) >= num(extendedValues.shellHeight)}
            onClick={() => props.onShell({
              outer_radius: num(extendedValues.shellOuterRadius), height: num(extendedValues.shellHeight),
              wall: num(extendedValues.shellWall), bottom: num(extendedValues.shellBottom), name: "Оболочка",
            })}
          >Создать оболочку</button>
        </>}

        {extendedTool === "draft" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.draftWidth} aria-label="Ширина основания уклона, мм" onChange={(event) => setExtendedValue("draftWidth", event.target.value)} /><span className="param-unit">ширина, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.draftDepth} aria-label="Глубина основания уклона, мм" onChange={(event) => setExtendedValue("draftDepth", event.target.value)} /><span className="param-unit">глубина, мм</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.draftHeight} aria-label="Высота тела с уклоном, мм" onChange={(event) => setExtendedValue("draftHeight", event.target.value)} /><span className="param-unit">высота, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.draftAngle} aria-label="Угол уклона, градусы" onChange={(event) => setExtendedValue("draftAngle", event.target.value)} /><span className="param-unit">угол, °</span></div>
          </div>
          <button
            className="btn" data-cmd="op.draft"
            disabled={num(extendedValues.draftWidth) <= 0 || num(extendedValues.draftDepth) <= 0 || num(extendedValues.draftHeight) <= 0 || Math.abs(num(extendedValues.draftAngle)) >= 89}
            onClick={() => props.onDraftPrism({
              width: num(extendedValues.draftWidth), depth: num(extendedValues.draftDepth),
              height: num(extendedValues.draftHeight), angle: num(extendedValues.draftAngle),
              name: "Тело с уклоном",
            })}
          >Создать тело с уклоном</button>
        </>}

        {extendedTool === "rib" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.baseLength} aria-label="Длина основания ребра, мм" onChange={(event) => setExtendedValue("baseLength", event.target.value)} /><span className="param-unit">основание X</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.baseWidth} aria-label="Ширина основания ребра, мм" onChange={(event) => setExtendedValue("baseWidth", event.target.value)} /><span className="param-unit">основание Y</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.baseThickness} aria-label="Толщина основания ребра, мм" onChange={(event) => setExtendedValue("baseThickness", event.target.value)} /><span className="param-unit">основание Z</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.ribLength} aria-label="Длина ребра, мм" onChange={(event) => setExtendedValue("ribLength", event.target.value)} /><span className="param-unit">длина ребра</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.ribHeight} aria-label="Высота ребра, мм" onChange={(event) => setExtendedValue("ribHeight", event.target.value)} /><span className="param-unit">высота ребра</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.ribWidth} aria-label="Толщина ребра, мм" onChange={(event) => setExtendedValue("ribWidth", event.target.value)} /><span className="param-unit">толщина ребра</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.ribOverlap} aria-label="Заглубление ребра, мм" onChange={(event) => setExtendedValue("ribOverlap", event.target.value)} /><span className="param-unit">заглубление</span></div>
          </div>
          <button
            className="btn" data-cmd="op.rib"
            disabled={num(extendedValues.baseLength) <= 0 || num(extendedValues.baseWidth) <= 0 || num(extendedValues.baseThickness) <= 0 || num(extendedValues.ribLength) <= 0 || num(extendedValues.ribLength) > num(extendedValues.baseLength) / 2 || num(extendedValues.ribHeight) <= 0 || num(extendedValues.ribWidth) <= 0 || num(extendedValues.ribWidth) > num(extendedValues.baseWidth) || num(extendedValues.ribOverlap) <= 0 || num(extendedValues.ribOverlap) >= num(extendedValues.baseThickness)}
            onClick={() => props.onRib({
              base_length: num(extendedValues.baseLength), base_width: num(extendedValues.baseWidth),
              base_thickness: num(extendedValues.baseThickness), rib_length: num(extendedValues.ribLength),
              rib_height: num(extendedValues.ribHeight), rib_width: num(extendedValues.ribWidth),
              overlap: num(extendedValues.ribOverlap), name: "Ребро жёсткости",
            })}
          >Создать ребро</button>
        </>}

        {extendedTool === "fit" && <>
          <div className="op-row">
            <select value={extendedValues.fitFixture} aria-label="Размерная fixture посадки" onChange={(event) => setExtendedValue("fitFixture", event.target.value)}>
              <option value="nut_m5">Гайка M5 — 8 × 4 мм</option>
              <option value="bearing_608">Подшипник 608 — Ø22 × 7 мм</option>
              <option value="heat_insert_m3">Термовставка M3 — Ø4,6 × 5 мм</option>
            </select>
            <select value={extendedValues.fitClearanceMode} aria-label="Смысл зазора посадки" onChange={(event) => setExtendedValue("fitClearanceMode", event.target.value)}>
              <option value="radial">Радиальный</option>
              <option value="diametral">Диаметральный</option>
              <option value="one_sided">Односторонний +X</option>
            </select>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.fitBodyLength} aria-label="Длина корпуса посадки, мм" onChange={(event) => setExtendedValue("fitBodyLength", event.target.value)} /><span className="param-unit">корпус X</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.fitBodyWidth} aria-label="Ширина корпуса посадки, мм" onChange={(event) => setExtendedValue("fitBodyWidth", event.target.value)} /><span className="param-unit">корпус Y</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.fitBodyHeight} aria-label="Высота корпуса посадки, мм" onChange={(event) => setExtendedValue("fitBodyHeight", event.target.value)} /><span className="param-unit">корпус Z</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.fitClearance} aria-label="Зазор посадки, мм" onChange={(event) => setExtendedValue("fitClearance", event.target.value)} /><span className="param-unit">зазор, мм</span></div>
          </div>
          <p className="hint">Fixture v1 хранит номинальные размеры явно. Радиальный зазор добавляется с двух сторон, диаметральный — к общему размеру, односторонний сохраняет сторону −X.</p>
          <button
            className="btn" data-cmd="op.fit_pocket"
            disabled={num(extendedValues.fitBodyLength) <= 0 || num(extendedValues.fitBodyWidth) <= 0 || num(extendedValues.fitBodyHeight) <= 0 || num(extendedValues.fitClearance) < 0}
            onClick={() => props.onFitPocket({
              fixture_id: extendedValues.fitFixture as FitFixtureId,
              fixture_version: "1",
              body_length: num(extendedValues.fitBodyLength),
              body_width: num(extendedValues.fitBodyWidth),
              body_height: num(extendedValues.fitBodyHeight),
              clearance: num(extendedValues.fitClearance),
              clearance_mode: extendedValues.fitClearanceMode as FitClearanceMode,
              name: "Посадка",
            })}
          >Создать посадку</button>
        </>}

        {extendedTool === "vector" && <>
          <div className="op-row">
            <select value={extendedValues.vectorFormat} aria-label="Формат векторного файла" onChange={(event) => setExtendedValue("vectorFormat", event.target.value)}>
              <option value="svg">SVG</option>
              <option value="dxf">DXF</option>
            </select>
            <div className="param-input op-field"><input value={extendedValues.vectorPath} aria-label="Путь к SVG или DXF" onChange={(event) => setExtendedValue("vectorPath", event.target.value)} /><span className="param-unit">файл</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.vectorHeight} aria-label="Высота векторного выдавливания, мм" onChange={(event) => setExtendedValue("vectorHeight", event.target.value)} /><span className="param-unit">высота, мм</span></div>
            {extendedValues.vectorFormat === "dxf" && <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.vectorUnitScale} aria-label="Масштаб unitless DXF в миллиметрах" onChange={(event) => setExtendedValue("vectorUnitScale", event.target.value)} /><span className="param-unit">мм / unit</span></div>}
          </div>
          <p className="hint">Исходник до 1 МБ встраивается в проект. Внешние SVG-ресурсы и неподдерживаемые DXF-сущности отклоняются.</p>
          <button
            className="btn" data-cmd="op.vector_extrude"
            disabled={!extendedValues.vectorPath.trim() || num(extendedValues.vectorHeight) <= 0 || (extendedValues.vectorFormat === "dxf" && num(extendedValues.vectorUnitScale) <= 0)}
            onClick={() => props.onVectorExtrude({
              path: extendedValues.vectorPath,
              format: extendedValues.vectorFormat as "svg" | "dxf",
              height: num(extendedValues.vectorHeight),
              unit_scale: extendedValues.vectorFormat === "dxf" ? num(extendedValues.vectorUnitScale) : undefined,
              name: "Векторное тело",
            })}
          >Импортировать и выдавить</button>
        </>}

        {extendedTool === "text" && <>
          <div className="op-row">
            <div className="param-input op-field"><input value={extendedValues.textValue} maxLength={80} aria-label="Текст рельефа" onChange={(event) => setExtendedValue("textValue", event.target.value)} /><span className="param-unit">текст</span></div>
            <select value={extendedValues.textMode} aria-label="Режим текстового рельефа" onChange={(event) => setExtendedValue("textMode", event.target.value)}>
              <option value="add">Выпуклый</option>
              <option value="cut">Гравировка</option>
            </select>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.textFontSize} aria-label="Размер текста, мм" onChange={(event) => setExtendedValue("textFontSize", event.target.value)} /><span className="param-unit">размер, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.textReliefHeight} aria-label="Высота или глубина текста, мм" onChange={(event) => setExtendedValue("textReliefHeight", event.target.value)} /><span className="param-unit">рельеф, мм</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.textBodyLength} aria-label="Длина основания текста, мм" onChange={(event) => setExtendedValue("textBodyLength", event.target.value)} /><span className="param-unit">основание X</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.textBodyWidth} aria-label="Ширина основания текста, мм" onChange={(event) => setExtendedValue("textBodyWidth", event.target.value)} /><span className="param-unit">основание Y</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.textBodyHeight} aria-label="Толщина основания текста, мм" onChange={(event) => setExtendedValue("textBodyHeight", event.target.value)} /><span className="param-unit">основание Z</span></div>
          </div>
          <p className="hint">JetBrains Mono 2.211 поставляется с приложением; скрытая подстановка другого шрифта запрещена.</p>
          <button
            className="btn" data-cmd="op.text_relief"
            disabled={!extendedValues.textValue || num(extendedValues.textFontSize) <= 0 || num(extendedValues.textReliefHeight) <= 0 || num(extendedValues.textBodyLength) <= 0 || num(extendedValues.textBodyWidth) <= 0 || num(extendedValues.textBodyHeight) <= 0 || (extendedValues.textMode === "cut" && num(extendedValues.textReliefHeight) >= num(extendedValues.textBodyHeight))}
            onClick={() => props.onTextRelief({
              text: extendedValues.textValue,
              font_size: num(extendedValues.textFontSize), relief_height: num(extendedValues.textReliefHeight),
              body_length: num(extendedValues.textBodyLength), body_width: num(extendedValues.textBodyWidth),
              body_height: num(extendedValues.textBodyHeight), mode: extendedValues.textMode as "add" | "cut",
              name: "Текстовый рельеф",
            })}
          >Создать текст</button>
        </>}

        {extendedTool === "thread" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.threadDiameter} aria-label="Наружный диаметр резьбы, мм" onChange={(event) => setExtendedValue("threadDiameter", event.target.value)} /><span className="param-unit">Ø резьбы</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.threadPitch} aria-label="Шаг резьбы, мм" onChange={(event) => setExtendedValue("threadPitch", event.target.value)} /><span className="param-unit">шаг, мм</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.threadLength} aria-label="Рабочая длина резьбы, мм" onChange={(event) => setExtendedValue("threadLength", event.target.value)} /><span className="param-unit">длина, мм</span></div>
          </div>
          <div className="op-row">
            <select value={extendedValues.threadHand} aria-label="Направление резьбы" onChange={(event) => setExtendedValue("threadHand", event.target.value)}>
              <option value="right">Правая</option>
              <option value="left">Левая</option>
            </select>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.threadClearance} aria-label="Диаметральный зазор резьбы, мм" onChange={(event) => setExtendedValue("threadClearance", event.target.value)} /><span className="param-unit">зазор Ø</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.threadNutHeight} aria-label="Высота гайки, мм" onChange={(event) => setExtendedValue("threadNutHeight", event.target.value)} /><span className="param-unit">гайка Z</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.threadNutAcrossFlats} aria-label="Размер гайки под ключ, мм" onChange={(event) => setExtendedValue("threadNutAcrossFlats", event.target.value)} /><span className="param-unit">под ключ</span></div>
          </div>
          <p className="hint">Строится настоящая однозаходная винтовая пара profile metric-60-v1. Зазор диаметральный; гладкий цилиндр и metadata не заменяют резьбу.</p>
          <button
            className="btn" data-cmd="op.thread_pair"
            disabled={num(extendedValues.threadDiameter) <= 0 || num(extendedValues.threadPitch) <= 0 || num(extendedValues.threadLength) < num(extendedValues.threadPitch) || num(extendedValues.threadClearance) <= 0 || num(extendedValues.threadNutHeight) <= 0 || num(extendedValues.threadNutHeight) >= num(extendedValues.threadLength) || num(extendedValues.threadNutAcrossFlats) <= num(extendedValues.threadDiameter) + num(extendedValues.threadClearance)}
            onClick={() => props.onThreadPair({
              profile_version: "metric-60-v1",
              major_diameter: num(extendedValues.threadDiameter), pitch: num(extendedValues.threadPitch),
              length: num(extendedValues.threadLength), hand: extendedValues.threadHand as "right" | "left",
              starts: 1, clearance: num(extendedValues.threadClearance),
              nut_height: num(extendedValues.threadNutHeight),
              nut_across_flats: num(extendedValues.threadNutAcrossFlats), name: "Резьбовая пара",
            })}
          >Создать резьбовую пару</button>
        </>}

        {extendedTool === "calibration" && <>
          <div className="op-row">
            <div className="param-input op-field"><input value={extendedValues.calibrationValues} aria-label="Ряд диаметральных зазоров, мм" onChange={(event) => setExtendedValue("calibrationValues", event.target.value)} /><span className="param-unit">зазоры через запятую</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.calibrationNominal} aria-label="Номинальный диаметр калибровки, мм" onChange={(event) => setExtendedValue("calibrationNominal", event.target.value)} /><span className="param-unit">Ø номинал</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.calibrationLength} aria-label="Длина калибровочного образца, мм" onChange={(event) => setExtendedValue("calibrationLength", event.target.value)} /><span className="param-unit">образец X</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.calibrationWidth} aria-label="Ширина калибровочного образца, мм" onChange={(event) => setExtendedValue("calibrationWidth", event.target.value)} /><span className="param-unit">образец Y</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.calibrationThickness} aria-label="Толщина калибровочного образца, мм" onChange={(event) => setExtendedValue("calibrationThickness", event.target.value)} /><span className="param-unit">образец Z</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.calibrationSpacing} aria-label="Шаг размещения калибровочных образцов, мм" onChange={(event) => setExtendedValue("calibrationSpacing", event.target.value)} /><span className="param-unit">шаг X</span></div>
            <div className="param-input op-field"><input value={extendedValues.calibrationProfile} aria-label="Имя профиля калибровки" onChange={(event) => setExtendedValue("calibrationProfile", event.target.value)} /><span className="param-unit">профиль</span></div>
          </div>
          <p className="hint">Каждый образец получает реальную BRep-метку значения. Профиль записывается в проект только по явному созданию этой серии и не меняет старые документы.</p>
          <button
            className="btn" data-cmd="op.clearance_calibration"
            disabled={!calibrationValuesValid || num(extendedValues.calibrationNominal) <= 0 || num(extendedValues.calibrationLength) <= 0 || num(extendedValues.calibrationWidth) <= 0 || num(extendedValues.calibrationThickness) <= 0 || num(extendedValues.calibrationSpacing) < num(extendedValues.calibrationLength)}
            onClick={() => props.onClearanceCalibration({
              values: calibrationValues,
              nominal_diameter: num(extendedValues.calibrationNominal),
              coupon_length: num(extendedValues.calibrationLength), coupon_width: num(extendedValues.calibrationWidth),
              thickness: num(extendedValues.calibrationThickness), spacing: num(extendedValues.calibrationSpacing),
              font_size: num(extendedValues.calibrationFontSize), label_height: num(extendedValues.calibrationLabelHeight),
              profile_name: extendedValues.calibrationProfile.trim() || undefined, name: "Калибровка зазоров",
            })}
          >Создать серию</button>
        </>}

        {extendedTool === "connector" && <>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.connectorLength} aria-label="Длина разделяемой детали, мм" onChange={(event) => setExtendedValue("connectorLength", event.target.value)} /><span className="param-unit">деталь X</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.connectorWidth} aria-label="Ширина разделяемой детали, мм" onChange={(event) => setExtendedValue("connectorWidth", event.target.value)} /><span className="param-unit">деталь Y</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.connectorHeight} aria-label="Высота разделяемой детали, мм" onChange={(event) => setExtendedValue("connectorHeight", event.target.value)} /><span className="param-unit">деталь Z</span></div>
          </div>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.connectorPinRadius} aria-label="Радиус соединительного штифта, мм" onChange={(event) => setExtendedValue("connectorPinRadius", event.target.value)} /><span className="param-unit">R штифта</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.connectorPinLength} aria-label="Длина соединительного штифта, мм" onChange={(event) => setExtendedValue("connectorPinLength", event.target.value)} /><span className="param-unit">длина штифта</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={extendedValues.connectorClearance} aria-label="Радиальный зазор соединителя, мм" onChange={(event) => setExtendedValue("connectorClearance", event.target.value)} /><span className="param-unit">зазор R</span></div>
          </div>
          <div className="op-row"><div className="param-input op-field"><input inputMode="decimal" value={extendedValues.connectorSeparation} aria-label="Зазор печатного размещения частей, мм" onChange={(event) => setExtendedValue("connectorSeparation", event.target.value)} /><span className="param-unit">разнос печати</span></div></div>
          <p className="hint">Две половины размещаются раздельно для печати. В операции хранится обратный assembly transform; ядро проверяет отсутствие пересечения штифтов с ответными отверстиями.</p>
          <button
            className="btn" data-cmd="op.split_connector_pair"
            disabled={num(extendedValues.connectorLength) <= 0 || num(extendedValues.connectorWidth) <= 0 || num(extendedValues.connectorHeight) <= 0 || num(extendedValues.connectorPinRadius) <= 0 || num(extendedValues.connectorPinLength) <= 0 || num(extendedValues.connectorClearance) <= 0 || num(extendedValues.connectorSeparation) <= 0}
            onClick={() => props.onSplitConnectorPair({
              length: num(extendedValues.connectorLength), width: num(extendedValues.connectorWidth),
              height: num(extendedValues.connectorHeight), pin_radius: num(extendedValues.connectorPinRadius),
              pin_length: num(extendedValues.connectorPinLength), radial_clearance: num(extendedValues.connectorClearance),
              print_separation: num(extendedValues.connectorSeparation), name: "Разделённая деталь",
            })}
          >Создать две части</button>
        </>}
      </InspectorSection>

      {props.selectedFace != null && props.faceArea != null && (
        <section className="face-info">
          <h3 className="panel-section">Выбранная грань</h3>
          <p>Грань {props.selectedFace} — площадь <strong>{fmtNum(props.faceArea)} мм²</strong></p>
          {props.pushPull.target ? (
            <div className="push-pull-panel">
              <div className="push-pull-summary">
                <span>{props.pushPull.target.label}</span>
                <strong>{fmtNum(props.pushPull.target.current)} мм</strong>
              </div>
              <div className="param-field">
                <label htmlFor="push-pull-value">Точный размер</label>
                <div className="param-input" data-cmd="parameter.set">
                  <input
                    id="push-pull-value"
                    inputMode="decimal"
                    value={props.pushPull.value}
                    aria-label={`${props.pushPull.target.label}, мм`}
                    onChange={(event) => props.onPushPullValue(event.target.value)}
                    onKeyDown={(event) => { if (event.key === "Enter") props.onApplyPushPull(); }}
                  />
                  <span className="param-unit">мм</span>
                </div>
              </div>
              <p className="push-pull-hint">
                Потяните оранжевый манипулятор или введите размер.
                {props.pushPull.target.symmetric && " Размер меняется симметрично относительно центра."}
              </p>
              {props.pushPull.dragging && <div className="push-pull-live">Предпросмотр: {props.pushPull.value} мм</div>}
              <div className="push-pull-actions">
                <button className="btn btn-primary" onClick={props.onApplyPushPull}>Применить</button>
                <button className="btn" onClick={props.onCancelPushPull}>Сбросить</button>
              </div>
            </div>
          ) : props.pushPull.reason ? (
            <p className="push-pull-hint">{props.pushPull.reason}</p>
          ) : null}
          {props.faceFeatureTarget && (<>
            <div className="face-feature-panel">
              <div className="face-feature-heading">
                <div>
                  <strong>Элемент на грани</strong>
                  <span>
                    {props.faceFeatureTarget.side > 0 ? "+" : "−"}
                    {props.faceFeatureTarget.axis?.toUpperCase()} · локальные оси {props.faceFeatureTarget.uLabel}/{props.faceFeatureTarget.vLabel}
                  </span>
                </div>
                {!faceFeatureOpen && (
                  <button
                    className="btn"
                    data-cmd="op.profile"
                    onClick={() => {
                      setFaceDomeOpen(false);
                      setSheetBendOpen(false);
                      props.onFaceDomePreview(null);
                      props.onSheetBendPreview(null);
                      setFaceFeatureOpen(true);
                    }}
                  >
                    Создать
                  </button>
                )}
              </div>
              {faceFeatureOpen && (
                <div className="face-feature-form">
                  <div className="op-row">
                    <select
                      value={faceFeatureMode}
                      aria-label="Режим элемента на грани"
                      onChange={(event) => setFaceFeatureMode(event.target.value as "add" | "cut")}
                    >
                      <option value="cut">Вырез / отверстие</option>
                      <option value="add">Добавить объём</option>
                    </select>
                    <select
                      value={faceFeatureKind}
                      aria-label="Профиль элемента на грани"
                      onChange={(event) => setFaceFeatureKind(event.target.value as FaceProfileKind)}
                    >
                      <option value="circle">Окружность</option>
                      <option value="rectangle">Прямоугольник</option>
                      <option value="slot">Паз</option>
                      <option value="ring">Кольцо</option>
                    </select>
                  </div>
                  <div className="op-row">
                    {faceFeatureKind === "rectangle" && (<>
                      <div className="param-input op-field">
                        <input inputMode="decimal" value={faceFeatureDims.width} aria-label="Ширина профиля на грани, мм" onChange={(event) => setFaceFeatureDims({ ...faceFeatureDims, width: event.target.value })} />
                        <span className="param-unit">ширина</span>
                      </div>
                      <div className="param-input op-field">
                        <input inputMode="decimal" value={faceFeatureDims.height} aria-label="Высота профиля на грани, мм" onChange={(event) => setFaceFeatureDims({ ...faceFeatureDims, height: event.target.value })} />
                        <span className="param-unit">высота</span>
                      </div>
                    </>)}
                    {faceFeatureKind === "circle" && (
                      <div className="param-input op-field">
                        <input inputMode="decimal" value={faceFeatureDims.diameter} aria-label="Диаметр отверстия на грани, мм" onChange={(event) => setFaceFeatureDims({ ...faceFeatureDims, diameter: event.target.value })} />
                        <span className="param-unit">Ø, мм</span>
                      </div>
                    )}
                    {faceFeatureKind === "ring" && (<>
                      <div className="param-input op-field">
                        <input inputMode="decimal" value={faceFeatureDims.outer_diameter} aria-label="Наружный диаметр кольца на грани, мм" onChange={(event) => setFaceFeatureDims({ ...faceFeatureDims, outer_diameter: event.target.value })} />
                        <span className="param-unit">Ø нар.</span>
                      </div>
                      <div className="param-input op-field">
                        <input inputMode="decimal" value={faceFeatureDims.inner_diameter} aria-label="Внутренний диаметр кольца на грани, мм" onChange={(event) => setFaceFeatureDims({ ...faceFeatureDims, inner_diameter: event.target.value })} />
                        <span className="param-unit">Ø вн.</span>
                      </div>
                    </>)}
                    {faceFeatureKind === "slot" && (<>
                      <div className="param-input op-field">
                        <input inputMode="decimal" value={faceFeatureDims.width} aria-label="Ширина паза на грани, мм" onChange={(event) => setFaceFeatureDims({ ...faceFeatureDims, width: event.target.value })} />
                        <span className="param-unit">ширина</span>
                      </div>
                      <div className="param-input op-field">
                        <input inputMode="decimal" value={faceFeatureDims.length} aria-label="Длина паза на грани, мм" onChange={(event) => setFaceFeatureDims({ ...faceFeatureDims, length: event.target.value })} />
                        <span className="param-unit">длина</span>
                      </div>
                    </>)}
                  </div>
                  <div className="op-row">
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={faceFeatureCenter.u} aria-label={`Смещение по ${props.faceFeatureTarget.uLabel}, мм`} onChange={(event) => setFaceFeatureCenter({ ...faceFeatureCenter, u: event.target.value })} />
                      <span className="param-unit">{props.faceFeatureTarget.uLabel}, мм</span>
                    </div>
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={faceFeatureCenter.v} aria-label={`Смещение по ${props.faceFeatureTarget.vLabel}, мм`} onChange={(event) => setFaceFeatureCenter({ ...faceFeatureCenter, v: event.target.value })} />
                      <span className="param-unit">{props.faceFeatureTarget.vLabel}, мм</span>
                    </div>
                  </div>
                  {faceFeatureMode === "cut" && (
                    <label className="keep-tool">
                      <input type="checkbox" checked={faceFeatureThrough} onChange={(event) => setFaceFeatureThrough(event.target.checked)} />
                      Сквозной вырез
                    </label>
                  )}
                  {(faceFeatureMode === "add" || !faceFeatureThrough) && (
                    <div className="param-input op-field face-feature-depth">
                      <input inputMode="decimal" value={faceFeatureDepth} aria-label="Глубина элемента на грани, мм" onChange={(event) => setFaceFeatureDepth(event.target.value)} />
                      <span className="param-unit">глубина, мм</span>
                    </div>
                  )}
                  {faceFeatureError ? (
                    <p className="error-inline" role="alert">{faceFeatureError}</p>
                  ) : (
                    <p className="face-feature-preview">Предпросмотр показан на сцене. Рабочая модель ещё не изменена.</p>
                  )}
                  <div className="push-pull-actions">
                    <button
                      className="btn btn-primary"
                      data-cmd="op.profile"
                      disabled={!faceFeatureRequest}
                      onClick={() => {
                        if (!faceFeatureRequest) return;
                        props.onFaceFeaturePreview(null);
                        props.onApplyFaceFeature(faceFeatureRequest);
                        setFaceFeatureOpen(false);
                      }}
                    >
                      {faceFeatureMode === "add" ? "Добавить" : "Вырезать"}
                    </button>
                    <button
                      className="btn"
                      onClick={() => {
                        setFaceFeatureOpen(false);
                        props.onFaceFeaturePreview(null);
                      }}
                    >
                      Отмена
                    </button>
                  </div>
                </div>
              )}
            </div>
            <div className="face-feature-panel">
              <div className="face-feature-heading">
                <div>
                  <strong>Выпуклость / вмятина</strong>
                  <span>Сферический сегмент с точными размерами</span>
                </div>
                {!faceDomeOpen && (
                  <button
                    className="btn"
                    data-cmd="op.face_dome"
                    onClick={() => {
                      setFaceFeatureOpen(false);
                      setSheetBendOpen(false);
                      props.onFaceFeaturePreview(null);
                      props.onSheetBendPreview(null);
                      setFaceDomeOpen(true);
                    }}
                  >
                    Создать
                  </button>
                )}
              </div>
              {faceDomeOpen && (
                <div className="face-feature-form">
                  <select
                    value={faceDomeMode}
                    aria-label="Режим сферического сегмента"
                    onChange={(event) => setFaceDomeMode(event.target.value as "add" | "cut")}
                  >
                    <option value="add">Выпуклость</option>
                    <option value="cut">Вмятина</option>
                  </select>
                  <div className="op-row">
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={faceDomeDiameter} aria-label="Диаметр сферического сегмента, мм" onChange={(event) => setFaceDomeDiameter(event.target.value)} />
                      <span className="param-unit">Ø, мм</span>
                    </div>
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={faceDomeHeight} aria-label="Высота сферического сегмента, мм" onChange={(event) => setFaceDomeHeight(event.target.value)} />
                      <span className="param-unit">высота, мм</span>
                    </div>
                  </div>
                  <div className="op-row">
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={faceDomeCenter.u} aria-label={`Смещение выпуклости по ${props.faceFeatureTarget.uLabel}, мм`} onChange={(event) => setFaceDomeCenter({ ...faceDomeCenter, u: event.target.value })} />
                      <span className="param-unit">{props.faceFeatureTarget.uLabel}, мм</span>
                    </div>
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={faceDomeCenter.v} aria-label={`Смещение выпуклости по ${props.faceFeatureTarget.vLabel}, мм`} onChange={(event) => setFaceDomeCenter({ ...faceDomeCenter, v: event.target.value })} />
                      <span className="param-unit">{props.faceFeatureTarget.vLabel}, мм</span>
                    </div>
                  </div>
                  {faceDomeError ? (
                    <p className="error-inline" role="alert">{faceDomeError}</p>
                  ) : (
                    <p className="face-feature-preview">Предпросмотр показан на сцене. Рабочая модель ещё не изменена.</p>
                  )}
                  <div className="push-pull-actions">
                    <button
                      className="btn btn-primary"
                      data-cmd="op.face_dome"
                      disabled={!faceDomeRequest}
                      onClick={() => {
                        if (!faceDomeRequest) return;
                        props.onFaceDomePreview(null);
                        props.onApplyFaceDome(faceDomeRequest);
                        setFaceDomeOpen(false);
                      }}
                    >
                      {faceDomeMode === "add" ? "Создать выпуклость" : "Создать вмятину"}
                    </button>
                    <button
                      className="btn"
                      onClick={() => {
                        setFaceDomeOpen(false);
                        props.onFaceDomePreview(null);
                      }}
                    >
                      Отмена
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>)}
          {props.sheetBendTarget && (
            <div className="face-feature-panel">
              <div className="face-feature-heading">
                <div>
                  <strong>{perpendicularFlangeBend ? "Изгиб фланца" : "Точный изгиб"}</strong>
                  <span>{perpendicularFlangeBend
                    ? "Перпендикулярная линия на выбранном фланце"
                    : "Sheet metal: угол, радиус и линия изгиба"}</span>
                </div>
                {!sheetBendOpen && (
                  <button
                    className="btn"
                    data-cmd="op.sheet_bend"
                    disabled={!!sheetBendStructuralReason}
                    title={sheetBendStructuralReason ?? "Создать изгиб"}
                    onClick={() => {
                      setFaceFeatureOpen(false);
                      setFaceDomeOpen(false);
                      props.onFaceFeaturePreview(null);
                      props.onFaceDomePreview(null);
                      setSheetBendOpen(true);
                    }}
                  >
                    Создать
                  </button>
                )}
              </div>
              {!sheetBendOpen && sheetBendStructuralReason && (
                <p className="push-pull-hint">{sheetBendStructuralReason}</p>
              )}
              {sheetBendOpen && (
                <div className="face-feature-form">
                  <div className="op-row">
                    <select
                      value={sheetBendAxis}
                      aria-label="Направление изгиба"
                      disabled={perpendicularFlangeBend}
                      onChange={(event) => setSheetBendAxis(event.target.value as "x" | "y")}
                    >
                      <option value="x">Сгибать по X · линия вдоль Y</option>
                      <option value="y">Сгибать по Y · линия вдоль X</option>
                    </select>
                    <select
                      value={sheetBendMovingSide}
                      aria-label="Подвижная сторона изгиба"
                      onChange={(event) => setSheetBendMovingSide(Number(event.target.value) as -1 | 1)}
                    >
                      <option value={1}>{`Сгибать +${sheetBendAxis.toUpperCase()}`}</option>
                      <option value={-1}>{`Сгибать −${sheetBendAxis.toUpperCase()}`}</option>
                    </select>
                  </div>
                  <div className="op-row">
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={sheetBendPosition} aria-label="Положение линии изгиба, мм" onChange={(event) => setSheetBendPosition(event.target.value)} />
                      <span className="param-unit">позиция, мм</span>
                    </div>
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={sheetBendAngle} aria-label="Угол изгиба, градусы" onChange={(event) => setSheetBendAngle(event.target.value)} />
                      <span className="param-unit">угол, °</span>
                    </div>
                  </div>
                  <div className="op-row">
                    <div className="param-input op-field">
                      <input inputMode="decimal" value={sheetBendRadius} aria-label="Внутренний радиус изгиба, мм" onChange={(event) => setSheetBendRadius(event.target.value)} />
                      <span className="param-unit">R вн., мм</span>
                    </div>
                    <select
                      value={sheetBendDirection}
                      aria-label={perpendicularFlangeBend
                        ? "Направление изгиба относительно выбранной грани"
                        : "Направление изгиба по Z"}
                      onChange={(event) => setSheetBendDirection(Number(event.target.value) as -1 | 1)}
                    >
                      <option value={1}>{perpendicularFlangeBend ? "К выбранной стороне" : "Вверх, +Z"}</option>
                      <option value={-1}>{perpendicularFlangeBend ? "От выбранной стороны" : "Вниз, −Z"}</option>
                    </select>
                  </div>
                  {sheetBendError ? (
                    <p className="error-inline" role="alert">{sheetBendError}</p>
                  ) : (
                    <p className="face-feature-preview">
                      {perpendicularFlangeBend
                        ? "Синий preview показывает локальную форму без контуров отверстий. Through-вырез целиком на прямом участке фланца сохраняется после commit."
                        : "Синий preview не показывает контуры вырезов. Прямоугольный through-вырез может пересекать до двух bend-зон, круглый, кольцевой или паз — одну."}
                    </p>
                  )}
                  <div className="push-pull-actions">
                    <button
                      className="btn btn-primary"
                      data-cmd="op.sheet_bend"
                      disabled={!sheetBendRequest}
                      onClick={() => {
                        if (!sheetBendRequest) return;
                        props.onSheetBendPreview(null);
                        props.onApplySheetBend(sheetBendRequest);
                        setSheetBendOpen(false);
                      }}
                    >
                      Создать изгиб
                    </button>
                    <button
                      className="btn"
                      onClick={() => {
                        setSheetBendOpen(false);
                        props.onSheetBendPreview(null);
                      }}
                    >
                      Отмена
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
          {!props.faceFeatureTarget && !props.sheetBendTarget && props.faceFeatureReason ? (
            <p className="push-pull-hint">{props.faceFeatureReason}</p>
          ) : null}
        </section>
      )}

      <InspectorSection title="Скругление и фаска — точные настройки">
        {!props.edgeTool.active ? (
          <div className="fillet-actions">
            <button
              className="btn" data-cmd="op.fillet" aria-label="Скруглить ребро"
              disabled={!doc?.stats?.is_valid || !!doc?.error}
              onClick={() => props.onStartEdgeTool("fillet")}
            >
              Скругление
            </button>
            <button
              className="btn" data-cmd="op.chamfer" aria-label="Создать фаску на ребре"
              disabled={!doc?.stats?.is_valid || !!doc?.error}
              onClick={() => props.onStartEdgeTool("chamfer")}
            >
              Фаска
            </button>
          </div>
        ) : (
          <div className="fillet-panel">
            <select
              aria-label="Тип обработки ребра"
              value={props.edgeTool.kind}
              onChange={(event) => props.onEdgeToolKind(event.target.value as EdgeFeatureKind)}
            >
              <option value="fillet">Скругление</option>
              <option value="chamfer">Фаска</option>
            </select>
            <p className="edge-pick-hint">
              Щёлкните прямое или криволинейное ребро на модели. Список ниже помогает выбрать и проверить нужное ребро.
            </p>
            {edges.length === 0 && <p className="panel-empty">Рёбра не найдены.</p>}
            <ul className="edge-list">
              {edges.map((e, i) => {
                const applied = edgeOperations.filter((operation) => sameEdge(operation.edge_ref!, e));
                const sel = props.edgeTool.selected && sameEdge(props.edgeTool.selected, e);
                const appliedLabel = applied.map((operation) =>
                  operation.op === "fillet" ? "скруглено" : "фаска").join(", ");
                return (
                  <li key={i}>
                    <button
                      className={`edge-row ${sel ? "edge-selected" : ""}`}
                      data-cmd={props.edgeTool.kind === "fillet" ? "op.fillet" : "op.chamfer"}
                      aria-label={`Ребро ${e.kind}, длина ${fmtNum(e.length)} мм${appliedLabel ? `, ${appliedLabel}` : ""}`}
                      onClick={() => props.onSelectEdge(e)}
                    >
                      <span className="edge-kind">{e.kind}</span>
                      <span className="edge-len">{fmtNum(e.length)} мм</span>
                      <span className="edge-mid">
                        ({e.midpoint.map((v) => fmtNum(v)).join("; ")})
                      </span>
                      {appliedLabel && <span className="history-badge">{appliedLabel}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="param-field">
              <label htmlFor="edge-feature-size">
                {props.edgeTool.kind === "fillet" ? "Радиус" : "Размер фаски"}
              </label>
              <div className="param-input">
                <input
                  id="edge-feature-size" inputMode="decimal"
                  value={props.edgeTool.size}
                  aria-label={props.edgeTool.kind === "fillet" ? "Радиус скругления, мм" : "Размер фаски, мм"}
                  onChange={(e) => props.onEdgeToolSize(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") props.onApplyEdgeTool(); }}
                />
                <span className="param-unit">мм</span>
              </div>
            </div>
            <div className="fillet-actions">
              <button
                className="btn btn-primary"
                data-cmd={props.edgeTool.kind === "fillet" ? "op.fillet" : "op.chamfer"}
                aria-label={props.edgeTool.kind === "fillet" ? "Применить скругление" : "Применить фаску"}
                disabled={!props.edgeTool.selected}
                onClick={props.onApplyEdgeTool}
              >
                {props.edgeTool.kind === "fillet" ? "Применить скругление" : "Применить фаску"}
              </button>
              <button className="btn" aria-label="Отменить выбор ребра" onClick={props.onCancelEdgeTool}>Отмена</button>
            </div>
          </div>
        )}
      </InspectorSection>

      <InspectorSection title="Тела, массивы и выравнивание">
        <details className="add-part">
          <summary className="btn" data-cmd="part.add" aria-label="Добавить деталь">Добавить деталь</summary>
          <ul className="template-list add-part-menu">
            {templates.map((t) => (
              <li key={t.template_id}>
                <button className="template-row" data-cmd="part.add" aria-label={`Добавить: ${t.title}`} onClick={() => props.onAddPart(t)}>
                  <span className="template-title">{t.title}</span>
                </button>
              </li>
            ))}
          </ul>
        </details>

        <div className="op-block">
          <div className="op-row">
            {([["union", "Объединить"], ["subtract", "Вычесть"], ["intersect", "Пересечь"]] as const).map(([kind, label]) => (
              <button
                key={kind} className="btn" data-cmd={`op.${kind}`}
                aria-label={label}
                disabled={!booleanReady}
                title={booleanReady ? label : "Сначала добавьте вторую деталь"}
                onClick={() => props.onBoolean(kind, keepTool)}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="keep-tool">
            <input type="checkbox" checked={keepTool} onChange={(e) => setKeepTool(e.target.checked)} />
            Сохранить инструмент
          </label>
          {booleanReady && targetPart && toolPart && (
            <p className="op-pair">Основное: {targetPart.name} · Инструмент: {toolPart.name}</p>
          )}
        </div>

        <div className="op-block">
          <span className="op-label">Массив</span>
          <div className="op-row">
            <div className="param-input op-field">
              <input inputMode="numeric" value={arrayCount} aria-label="Количество копий" onChange={(e) => setArrayCount(e.target.value)} />
              <span className="param-unit">шт</span>
            </div>
            {(["x", "y", "z"] as const).map((a) => (
              <div className="param-input op-field" key={a}>
                <input inputMode="decimal" value={arrayStep[a]} aria-label={`Шаг ${a.toUpperCase()}, мм`} onChange={(e) => setArrayStep({ ...arrayStep, [a]: e.target.value })} />
                <span className="param-unit">{a.toUpperCase()}</span>
              </div>
            ))}
          </div>
          <button
            className="btn" data-cmd="op.array" aria-label="Создать массив"
            disabled={!targetPart || parseInt(arrayCount, 10) < 2}
            title={!targetPart ? "Сначала создайте деталь" : parseInt(arrayCount, 10) < 2 ? "Количество — не меньше 2" : "Создать массив"}
            onClick={() => props.onArray(parseInt(arrayCount, 10), [num(arrayStep.x), num(arrayStep.y), num(arrayStep.z)])}
          >
            Массив
          </button>
        </div>

        <div className="op-block">
          <span className="op-label">Зеркало</span>
          <div className="op-row">
            <select value={mirrorPlane} aria-label="Плоскость зеркала" onChange={(e) => setMirrorPlane(e.target.value as "XY" | "XZ" | "YZ")}>
              <option value="XY">XY</option><option value="XZ">XZ</option><option value="YZ">YZ</option>
            </select>
            <button
              className="btn" data-cmd="op.mirror" aria-label="Зеркалировать деталь"
              disabled={!targetPart} title={!targetPart ? "Сначала создайте деталь" : "Зеркалировать"}
              onClick={() => props.onMirror(mirrorPlane)}
            >
              Зеркало
            </button>
          </div>
        </div>

        <div className="op-block">
          <span className="op-label">Разделить деталь</span>
          <div className="op-row">
            <select value={splitPlane} aria-label="Плоскость разреза" onChange={(e) => setSplitPlane(e.target.value as "XY" | "XZ" | "YZ")}>
              <option value="XY">XY</option><option value="XZ">XZ</option><option value="YZ">YZ</option>
            </select>
            <div className="param-input op-field">
              <input inputMode="decimal" value={splitOffset} aria-label="Смещение плоскости, мм" onChange={(e) => setSplitOffset(e.target.value)} />
              <span className="param-unit">мм</span>
            </div>
            <button
              className="btn" data-cmd="op.split" aria-label="Разделить деталь"
              disabled={!targetPart} title={!targetPart ? "Сначала создайте деталь" : "Разделить деталь"}
              onClick={() => props.onSplit(splitPlane, num(splitOffset))}
            >
              Разделить
            </button>
          </div>
        </div>

        <div className="op-block">
          <span className="op-label">Профиль и выдавливание</span>
          <div className="op-row">
            <select value={profileKind} aria-label="Тип профиля" onChange={(e) => setProfileKind(e.target.value as typeof profileKind)}>
              <option value="rectangle">Прямоугольник</option>
              <option value="circle">Окружность</option>
              <option value="ring">Кольцо</option>
              <option value="slot">Паз</option>
            </select>
            <select value={profilePlane} aria-label="Плоскость профиля" onChange={(e) => setProfilePlane(e.target.value as "XY" | "XZ" | "YZ")}>
              <option value="XY">XY</option><option value="XZ">XZ</option><option value="YZ">YZ</option>
            </select>
          </div>
          <div className="op-row">
            {profileKind === "rectangle" && (<>
              <div className="param-input op-field"><input inputMode="decimal" value={profileDims.width} aria-label="Ширина X, мм" onChange={(e) => setProfileDims({ ...profileDims, width: e.target.value })} /><span className="param-unit">X, мм</span></div>
              <div className="param-input op-field"><input inputMode="decimal" value={profileDims.height} aria-label="Высота Y, мм" onChange={(e) => setProfileDims({ ...profileDims, height: e.target.value })} /><span className="param-unit">Y, мм</span></div>
            </>)}
            {profileKind === "circle" && (
              <div className="param-input op-field"><input inputMode="decimal" value={profileDims.diameter} aria-label="Диаметр, мм" onChange={(e) => setProfileDims({ ...profileDims, diameter: e.target.value })} /><span className="param-unit">Ø, мм</span></div>
            )}
            {profileKind === "ring" && (<>
              <div className="param-input op-field"><input inputMode="decimal" value={profileDims.outer_diameter} aria-label="Наружный диаметр, мм" onChange={(e) => setProfileDims({ ...profileDims, outer_diameter: e.target.value })} /><span className="param-unit">Ø нар, мм</span></div>
              <div className="param-input op-field"><input inputMode="decimal" value={profileDims.inner_diameter} aria-label="Внутренний диаметр, мм" onChange={(e) => setProfileDims({ ...profileDims, inner_diameter: e.target.value })} /><span className="param-unit">Ø вн, мм</span></div>
            </>)}
            {profileKind === "slot" && (<>
              <div className="param-input op-field"><input inputMode="decimal" value={profileDims.slot_width} aria-label="Ширина паза, мм" onChange={(e) => setProfileDims({ ...profileDims, slot_width: e.target.value })} /><span className="param-unit">ширина, мм</span></div>
              <div className="param-input op-field"><input inputMode="decimal" value={profileDims.slot_length} aria-label="Длина паза, мм" onChange={(e) => setProfileDims({ ...profileDims, slot_length: e.target.value })} /><span className="param-unit">длина, мм</span></div>
            </>)}
          </div>
          {profileKind === "slot" && num(profileDims.slot_length) <= num(profileDims.slot_width) && (
            <p className="op-pair">Длина должна быть больше ширины.</p>
          )}
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="decimal" value={profileCenter.x} aria-label="Центр X, мм" onChange={(e) => setProfileCenter({ ...profileCenter, x: e.target.value })} /><span className="param-unit">ц. X</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={profileCenter.y} aria-label="Центр Y, мм" onChange={(e) => setProfileCenter({ ...profileCenter, y: e.target.value })} /><span className="param-unit">ц. Y</span></div>
          </div>
          <div className="op-row">
            <select value={profileMode} aria-label="Режим выдавливания" onChange={(e) => setProfileMode(e.target.value as "add" | "cut")}>
              <option value="add">Добавить объём</option>
              <option value="cut">Вырезать</option>
            </select>
            {profileMode === "cut" && (
              <label className="keep-tool">
                <input type="checkbox" checked={profileThrough} onChange={(e) => setProfileThrough(e.target.checked)} />
                Сквозной вырез
              </label>
            )}
          </div>
          {(profileMode === "add" || !profileThrough) && (
            <div className="op-row">
              <div className="param-input op-field"><input inputMode="decimal" value={profileDepth} aria-label="Глубина, мм" onChange={(e) => setProfileDepth(e.target.value)} /><span className="param-unit">глубина, мм</span></div>
            </div>
          )}
          <button
            className="btn" data-cmd="op.profile" aria-label="Выдавить профиль"
            disabled={profileMode === "add" ? num(profileDepth) <= 0 : !targetPart}
            title={profileMode === "cut" && !targetPart ? "Сначала создайте деталь" : "Выдавить профиль"}
            onClick={() => {
              const profile: Record<string, unknown> = { kind: profileKind, center: [num(profileCenter.x), num(profileCenter.y)] };
              if (profileKind === "rectangle") { profile.width = num(profileDims.width); profile.height = num(profileDims.height); }
              if (profileKind === "circle") profile.diameter = num(profileDims.diameter);
              if (profileKind === "ring") { profile.outer_diameter = num(profileDims.outer_diameter); profile.inner_diameter = num(profileDims.inner_diameter); }
              if (profileKind === "slot") { profile.width = num(profileDims.slot_width); profile.length = num(profileDims.slot_length); }
              props.onProfileExtrude({
                mode: profileMode,
                plane: profilePlane,
                profile,
                depth: profileMode === "add" ? num(profileDepth) : profileThrough ? "through" : num(profileDepth),
                target_id: profileMode === "cut" ? targetPart?.part_id : undefined,
              });
            }}
          >
            Выдавить
          </button>
        </div>

        <div className="op-block">
          <span className="op-label">Переместить</span>
          <div className="op-row">
            {(["x", "y", "z"] as const).map((a) => (
              <div className="param-input op-field" key={a}>
                <input inputMode="decimal" value={translate[a]} aria-label={`Сдвиг ${a.toUpperCase()}, мм`} onChange={(e) => setTranslate({ ...translate, [a]: e.target.value })} />
                <span className="param-unit">{a.toUpperCase()}, мм</span>
              </div>
            ))}
            <button
              className="btn" data-cmd="op.transform" aria-label="Переместить деталь"
              disabled={!targetPart} title={!targetPart ? "Сначала создайте деталь" : "Переместить деталь"}
              onClick={() => props.onTransform([num(translate.x), num(translate.y), num(translate.z)])}
            >
              Переместить
            </button>
          </div>
        </div>

        <div className="op-block">
          <span className="op-label">Круговой массив</span>
          <div className="op-row">
            <div className="param-input op-field"><input inputMode="numeric" value={circCount} aria-label="Количество копий" onChange={(e) => setCircCount(e.target.value)} /><span className="param-unit">шт</span></div>
            <div className="param-input op-field"><input inputMode="decimal" value={circAngle} aria-label="Полный угол, градусы" onChange={(e) => setCircAngle(e.target.value)} /><span className="param-unit">°</span></div>
          </div>
          <div className="op-row">
            {(["x", "y", "z"] as const).map((a) => (
              <div className="param-input op-field" key={a}>
                <input inputMode="decimal" value={circCenter[a]} aria-label={`Центр ${a.toUpperCase()}, мм`} onChange={(e) => setCircCenter({ ...circCenter, [a]: e.target.value })} />
                <span className="param-unit">{a.toUpperCase()}</span>
              </div>
            ))}
          </div>
          <button
            className="btn" data-cmd="op.array_circular" aria-label="Создать круговой массив"
            disabled={!targetPart || parseInt(circCount, 10) < 2}
            title={!targetPart ? "Сначала создайте деталь" : parseInt(circCount, 10) < 2 ? "Количество — не меньше 2" : "Создать круговой массив"}
            onClick={() => props.onArrayCircular(parseInt(circCount, 10), num(circAngle), [num(circCenter.x), num(circCenter.y), num(circCenter.z)])}
          >
            Круговой массив
          </button>
        </div>

        <div className="op-block">
          <span className="op-label">Выровнять</span>
          <div className="op-row">
            <select value={alignAxis} aria-label="Ось выравнивания" onChange={(e) => setAlignAxis(e.target.value as "x" | "y" | "z")}>
              <option value="x">X</option><option value="y">Y</option><option value="z">Z</option>
            </select>
            <select value={alignMode} aria-label="Режим выравнивания" onChange={(e) => setAlignMode(e.target.value as "center" | "min" | "max")}>
              <option value="center">по центру</option>
              <option value="min">по минимуму</option>
              <option value="max">по максимуму</option>
            </select>
            <div className="param-input op-field"><input inputMode="decimal" value={alignValue} aria-label="Значение, мм" onChange={(e) => setAlignValue(e.target.value)} /><span className="param-unit">мм</span></div>
            <button
              className="btn" data-cmd="op.align" aria-label="Выровнять деталь"
              disabled={!targetPart} title={!targetPart ? "Сначала создайте деталь" : "Выровнять деталь"}
              onClick={() => props.onAlign(alignAxis, alignMode, num(alignValue))}
            >
              Выровнять
            </button>
          </div>
        </div>
      </InspectorSection>

      <InspectorSection title="Измерения">
        <button
          className="btn" data-cmd="measure.run" aria-label="Обновить измерения"
          disabled={!doc?.stats?.is_valid || props.measureBusy}
          title={!doc?.stats?.is_valid ? "Сначала создайте деталь" : "Обновить измерения"}
          onClick={props.onMeasure}
        >
          {props.measureBusy ? "Измерение…" : "Обновить измерения"}
        </button>
        {props.measureResult?.bbox && (
          <div className="measure-result">
            <p>
              Габарит: {fmtNum(props.measureResult.bbox[3] - props.measureResult.bbox[0])} × {fmtNum(props.measureResult.bbox[4] - props.measureResult.bbox[1])} × {fmtNum(props.measureResult.bbox[5] - props.measureResult.bbox[2])} мм
            </p>
            {props.measureResult.volume != null && <p>Объём: {fmtNum(props.measureResult.volume)} мм³</p>}
            <p>Тел: {doc?.stats?.solid_count ?? "—"}</p>
            <p className="check-note">Источник: точная геометрия (BRep)</p>
          </div>
        )}
        <button
          className="btn" data-cmd="measure.run" aria-label="Измерить диаметр выбранной грани"
          disabled={props.selectedFace == null || props.measureBusy}
          title={props.selectedFace == null ? "Сначала выберите грань на сцене" : "Измерить диаметр грани"}
          onClick={props.onMeasureFace}
        >
          Диаметр грани
        </button>
        {props.measureResult?.faceDiameter != null && (
          <p className="measure-result">Диаметр грани {props.selectedFace}: {fmtNum(props.measureResult.faceDiameter)} мм</p>
        )}
        {props.measureResult?.faceError && (
          <p className="error-inline" role="alert">{props.measureResult.faceError}</p>
        )}
        <div className="op-block">
          <span className="op-label">Расстояние между точками</span>
          <div className="op-row">
            {(["x", "y", "z"] as const).map((a) => (
              <div className="param-input op-field" key={`p0-${a}`}>
                <input inputMode="decimal" value={distP0[a]} aria-label={`Точка 1, ${a.toUpperCase()}, мм`} onChange={(e) => setDistP0({ ...distP0, [a]: e.target.value })} />
                <span className="param-unit">{a.toUpperCase()}₁</span>
              </div>
            ))}
          </div>
          <div className="op-row">
            {(["x", "y", "z"] as const).map((a) => (
              <div className="param-input op-field" key={`p1-${a}`}>
                <input inputMode="decimal" value={distP1[a]} aria-label={`Точка 2, ${a.toUpperCase()}, мм`} onChange={(e) => setDistP1({ ...distP1, [a]: e.target.value })} />
                <span className="param-unit">{a.toUpperCase()}₂</span>
              </div>
            ))}
          </div>
          <button
            className="btn" data-cmd="measure.run" aria-label="Измерить расстояние"
            disabled={!doc?.stats?.is_valid || props.measureBusy}
            onClick={() => props.onMeasureDistance(
              [num(distP0.x), num(distP0.y), num(distP0.z)],
              [num(distP1.x), num(distP1.y), num(distP1.z)]
            )}
          >
            Измерить расстояние
          </button>
          {props.measureResult?.distance != null && (
            <p className="measure-result">Расстояние: {fmtNum(props.measureResult.distance)} мм</p>
          )}
        </div>
      </InspectorSection>

      <InspectorSection title="Проверка перед печатью">
        <div className="printer-row">
          {(["x", "y", "z"] as const).map((axis) => (
            <div className="param-input printer-field" key={axis}>
              <input
                inputMode="decimal" value={printer[axis]}
                aria-label={`Габарит принтера ${axis.toUpperCase()}, мм`}
                onChange={(e) => savePrinter({ ...printer, [axis]: e.target.value })}
              />
              <span className="param-unit">{axis.toUpperCase()}, мм</span>
            </div>
          ))}
        </div>
        <button
          className="btn" data-cmd="check.print" aria-label="Проверить перед печатью"
          disabled={!doc?.stats?.is_valid || props.printBusy}
          onClick={() => props.onPrintCheck({
            x: Number(printer.x.replace(",", ".")) || 220,
            y: Number(printer.y.replace(",", ".")) || 220,
            z: Number(printer.z.replace(",", ".")) || 250,
          })}
        >
          {props.printBusy ? "Проверка…" : "Проверить"}
        </button>
        {props.printChecks && (
          <>
            <ul className="check-list">
              {props.printChecks.map((c) => (
                <li key={c.id} className={`check-row check-${c.status}`}>
                  <span className="check-status">
                    {c.status === "pass" ? "Пройдено" : c.status === "fail" ? "Ошибка" : "Не проверено"}
                  </span>
                  <span className="check-title">{c.title}</span>
                  {c.detail && <span className="check-detail">{c.detail}</span>}
                </li>
              ))}
            </ul>
            <p className="check-note">«Проверки пройдены» означает только перечисленные проверки.</p>
          </>
        )}
      </InspectorSection>

      <InspectorSection title="Импорт модели" reveal={props.importPreview != null}>
        <div className="io-row">
          <input value={importPath} aria-label="Путь к импортируемой модели" onChange={(e) => setImportPath(e.target.value)} />
          <select
            value={importFormat} aria-label="Формат импорта"
            onChange={(e) => setImportFormat(e.target.value as "step" | "stl")}
          >
            <option value="step">STEP</option>
            <option value="stl">STL</option>
          </select>
        </div>
        {!props.importPreview ? (
          <button
            className="btn" data-cmd="io.import" aria-label="Импортировать модель"
            disabled={props.importBusy}
            onClick={() => props.onImport(importPath, importFormat, importFormat === "step" ? undefined : undefined)}
          >
            {props.importBusy ? "Импорт…" : "Импортировать"}
          </button>
        ) : (
          <div className="import-preview">
            {importFormat === "stl" && (previewBbox || previewExt) ? (
              <>
                <p>
                  Габарит сетки: {previewBbox
                    ? `${fmtNum(previewBbox[3] - previewBbox[0])} × ${fmtNum(previewBbox[4] - previewBbox[1])} × ${fmtNum(previewBbox[5] - previewBbox[2])}`
                    : `${fmtNum(previewExt![0])} × ${fmtNum(previewExt![1])} × ${fmtNum(previewExt![2])}`}.
                  Выберите единицы исходного файла:
                </p>
                <div className="fillet-actions">
                  <button className="btn btn-primary" data-cmd="io.mesh.apply" aria-label="Единицы — миллиметры" onClick={() => props.onApplyMeshImport(importPath, 1)}>
                    мм (×1)
                  </button>
                  <button className="btn" data-cmd="io.mesh.apply" aria-label="Единицы — дюймы" onClick={() => props.onApplyMeshImport(importPath, 25.4)}>
                    дюймы (×25,4)
                  </button>
                  <button className="btn" aria-label="Отменить импорт" onClick={props.onCancelImportPreview}>Отмена</button>
                </div>
              </>
            ) : (
              <p>Модель импортирована.</p>
            )}
          </div>
        )}
      </InspectorSection>

      {doc?.stats?.mesh_mode && <InspectorSection title="Работа с сеткой" reveal>
        <p className="hint">Исходник встроен в проект. Операции остаются mesh-операциями и не создают фиктивную параметрическую BRep-историю.</p>
        {doc.stats.mesh_diagnostics && <div className="param-hint" role="status">
          Треугольников: {doc.stats.triangle_count}; компонент: {doc.stats.mesh_diagnostics.components}; открытых рёбер: {doc.stats.mesh_diagnostics.boundary_edges}; self-intersection: не проверено.
        </div>}
        <div className="op-row">
          {(["x", "y", "z"] as const).map((axis) => <div className="param-input op-field" key={`mesh-${axis}`}>
            <input inputMode="decimal" value={meshTranslate[axis]} aria-label={`Mesh translate ${axis.toUpperCase()}, мм`} onChange={(event) => setMeshTranslate({ ...meshTranslate, [axis]: event.target.value })} />
            <span className="param-unit">{axis.toUpperCase()}, мм</span>
          </div>)}
        </div>
        <div className="op-row">
          <div className="param-input op-field"><input inputMode="decimal" value={meshScale} aria-label="Mesh scale" onChange={(event) => setMeshScale(event.target.value)} /><span className="param-unit">scale</span></div>
          <button className="btn" data-cmd="op.mesh.transform" disabled={num(meshScale) <= 0} onClick={() => props.onMeshTransform([num(meshTranslate.x), num(meshTranslate.y), num(meshTranslate.z)], num(meshScale))}>Трансформировать</button>
        </div>
        <div className="op-row">
          <button className="btn" data-cmd="op.mesh.repair" onClick={props.onMeshRepair}>Закрыть поддерживаемое отверстие</button>
        </div>
        <div className="op-row">
          <div className="param-input op-field"><input inputMode="decimal" value={meshTargetRatio} aria-label="Целевая доля треугольников" onChange={(event) => setMeshTargetRatio(event.target.value)} /><span className="param-unit">ratio</span></div>
          <button className="btn" data-cmd="op.mesh.decimate" disabled={num(meshTargetRatio) <= 0 || num(meshTargetRatio) >= 1} onClick={() => props.onMeshDecimate(num(meshTargetRatio))}>Упростить mesh</button>
        </div>
      </InspectorSection>}

      <InspectorSection title="Рельеф по изображению" reveal={props.imageReliefPreview != null}>
        <p className="hint">Experimental mesh-only workflow. Результат не считается точной инженерной деталью.</p>
        <div className="io-row"><input value={imagePath} aria-label="Путь к изображению relief" onChange={(event) => setImagePath(event.target.value)} /></div>
        <div className="op-row">
          <div className="param-input op-field"><input inputMode="decimal" value={imageWidth} aria-label="Ширина relief, мм" onChange={(event) => setImageWidth(event.target.value)} /><span className="param-unit">ширина, мм</span></div>
          <div className="param-input op-field"><input inputMode="decimal" value={imageReliefHeight} aria-label="Высота relief, мм" onChange={(event) => setImageReliefHeight(event.target.value)} /><span className="param-unit">рельеф, мм</span></div>
          <div className="param-input op-field"><input inputMode="decimal" value={imageBaseThickness} aria-label="Основание relief, мм" onChange={(event) => setImageBaseThickness(event.target.value)} /><span className="param-unit">основание, мм</span></div>
        </div>
        <div className="op-row">
          <div className="param-input op-field"><input inputMode="numeric" value={imageSamples} aria-label="Разрешение relief" onChange={(event) => setImageSamples(event.target.value)} /><span className="param-unit">samples</span></div>
          <div className="param-input op-field"><input inputMode="numeric" value={imageSeed} aria-label="Seed relief" onChange={(event) => setImageSeed(event.target.value)} /><span className="param-unit">seed</span></div>
          <div className="param-input op-field"><input inputMode="decimal" value={imageNoise} aria-label="Noise relief" onChange={(event) => setImageNoise(event.target.value)} /><span className="param-unit">noise</span></div>
        </div>
        <label className="check-label"><input type="checkbox" checked={imageInvert} onChange={(event) => setImageInvert(event.target.checked)} /> Инвертировать высоту</label>
        {props.imageReliefPreview && <div className="param-hint" role="status">
          Preview: {props.imageReliefPreview.stats.triangle_count} треугольников; model heightmap-luminance-v1; source {props.imageReliefPreview.source_sha256.slice(0, 12)}…
        </div>}
        <div className="op-row">
          <button
            className="btn" data-cmd="op.image_relief.preview"
            disabled={num(imageWidth) <= 0 || num(imageReliefHeight) <= 0 || num(imageBaseThickness) <= 0 || num(imageSamples) < 8 || num(imageSamples) > 192 || num(imageNoise) < 0 || num(imageNoise) > 0.2}
            onClick={() => props.onImageReliefPreview({
              path: imagePath, model: "heightmap-luminance-v1", seed: Math.trunc(num(imageSeed)),
              width_mm: num(imageWidth), relief_height: num(imageReliefHeight),
              base_thickness: num(imageBaseThickness), samples: Math.trunc(num(imageSamples)),
              noise_strength: num(imageNoise), invert: imageInvert,
            })}
          >Preview</button>
          {props.imageReliefPreview && <button
            className="btn btn-primary" data-cmd="op.image_relief.apply"
            onClick={() => props.onImageReliefApply({
              path: imagePath, model: "heightmap-luminance-v1", seed: Math.trunc(num(imageSeed)),
              width_mm: num(imageWidth), relief_height: num(imageReliefHeight),
              base_thickness: num(imageBaseThickness), samples: Math.trunc(num(imageSamples)),
              noise_strength: num(imageNoise), invert: imageInvert,
            }, props.imageReliefPreview!.source_sha256)}
          >Apply</button>}
          {props.imageReliefPreview && <button className="btn" onClick={props.onCancelImageReliefPreview}>Отмена</button>}
        </div>
      </InspectorSection>

      <InspectorSection title="Файл проекта и экспорт" className="io-forms">
        <div className="io-row">
          <input value={props.savePath} aria-label="Путь сохранения проекта" onChange={(e) => props.setSavePath(e.target.value)} />
          <button className="btn" data-cmd="doc.save" aria-label="Сохранить проект" disabled={!doc} onClick={props.onSave}>Сохранить</button>
        </div>
        <div className="io-row">
          <input value={props.openPath} aria-label="Путь открытия проекта" onChange={(e) => props.setOpenPath(e.target.value)} />
          <button className="btn" data-cmd="doc.open" aria-label="Открыть проект" onClick={props.onOpen}>Открыть</button>
        </div>
        <h3 className="panel-section">Экспорт</h3>
        <div className="io-row">
          <input value={props.exportPath} aria-label="Путь экспорта" onChange={(e) => props.setExportPath(e.target.value)} />
        </div>
        <div className="export-formats">
          {(["stl", "step", "3mf"] as const).map((f) => (
            <button
              key={f} className="btn" data-cmd={`export.${f}`}
              aria-label={`Экспортировать ${f.toUpperCase()}`}
              disabled={!doc?.stats?.is_valid || (f === "step" && !!doc?.stats?.mesh_mode)}
              onClick={() => props.onExport(f)}
            >
              {f.toUpperCase()}
            </button>
          ))}
        </div>
      </InspectorSection>
    </aside>
  );
}

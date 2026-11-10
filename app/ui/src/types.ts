export interface GeoError {
  code: string;
  message: string;
  detail?: string;
}

export interface EdgeRef {
  solid_index: number;
  kind: string;
  length: number;
  midpoint: [number, number, number];
  p0?: [number, number, number] | null;
  p1?: [number, number, number] | null;
  points?: Point3[];
}

export interface Operation {
  op: string;
  enabled?: boolean;
  size?: [number, number, number];
  anchor?: [-1 | 1, -1 | 1, -1 | 1];
  separate?: boolean;
  radius?: number;
  distance?: number;
  edge_ref?: EdgeRef;
  target_id?: string;
  part_id?: string;
  mode?: "add" | "cut";
  face_ref?: FaceFeatureRef | FaceOffsetRef;
  profile?: FaceFeatureProfile | SketchProfile;
  dimension_bindings?: DimensionBindings;
  sketch?: ConstrainedSketch;
  drag?: SketchDrag;
  depth?: number | "through";
  center?: [number, number];
  diameter?: number;
  height?: number;
  bend_axis?: "x" | "y";
  position?: number;
  angle?: number;
  inside_radius?: number;
  moving_side?: -1 | 1;
  direction?: -1 | 1;
  plane?: "XY" | "XZ" | "YZ";
  result_id?: string;
  name?: string;
  axis?: RevolveAxis;
  section?: SweepSection;
  path?: SweepPath;
  sections?: LoftSection[];
  ruled?: boolean;
  frenet?: boolean;
  outer_radius?: number;
  wall?: number;
  bottom?: number;
  width?: number;
  base_length?: number;
  base_width?: number;
  base_thickness?: number;
  rib_length?: number;
  rib_height?: number;
  rib_width?: number;
  overlap?: number;
  fixture_id?: FitFixtureId;
  fixture_version?: string;
  body_length?: number;
  body_width?: number;
  body_height?: number;
  clearance?: number;
  clearance_mode?: FitClearanceMode;
  pocket_depth?: number;
  format?: "svg" | "dxf";
  source_text?: string;
  unit_scale?: number;
  text?: string;
  font_size?: number;
  relief_height?: number;
  profile_version?: string;
  major_diameter?: number;
  pitch?: number;
  length?: number;
  hand?: "right" | "left";
  starts?: number;
  nut_height?: number;
  nut_across_flats?: number;
  values?: number[];
  nominal_diameter?: number;
  coupon_length?: number;
  coupon_width?: number;
  thickness?: number;
  spacing?: number;
  label_height?: number;
  profile_name?: string;
  pin_radius?: number;
  pin_length?: number;
  radial_clearance?: number;
  print_separation?: number;
}

export type Point2 = [number, number];
export type Point3 = [number, number, number];

export type SketchContour =
  | { kind: "polygon"; points: Point2[] }
  | { kind: "circle"; center: Point2; radius: number }
  | {
      kind: "segments";
      segments: Array<
        | { type: "line"; start: Point2; end: Point2 }
        | { type: "arc"; start: Point2; mid: Point2; end: Point2 }
      >;
    };

export interface SketchProfile {
  regions: Array<{ outer: SketchContour; holes: SketchContour[] }>;
}

export interface RevolveAxis {
  point: Point3;
  direction: Point3;
}

export interface SweepSection {
  kind: "circle";
  radius: number;
}

export interface SweepPath {
  points: Point3[];
}

export interface LoftSection {
  plane: "XY" | "XZ" | "YZ";
  offset: number;
  profile: SketchProfile;
}

export interface SketchExtrudeArgs {
  profile: SketchProfile;
  plane: "XY" | "XZ" | "YZ";
  depth: number;
  result_id?: string;
  name?: string;
}

export type ConstrainedSketchEntity =
  | { id: string; type: "line"; start: Point2; end: Point2 }
  | { id: string; type: "arc"; start: Point2; mid: Point2; end: Point2 }
  | { id: string; type: "circle"; center: Point2; radius: number };

export type SketchPointRef = [string, "start" | "end" | "mid" | "center"];

export type SketchConstraint =
  | { type: "coincident"; a: SketchPointRef; b: SketchPointRef }
  | { type: "horizontal" | "vertical"; entity: string }
  | { type: "parallel" | "perpendicular" | "equal"; a: string; b: string }
  | { type: "tangent"; line: string; circle: string; side?: -1 | 1 }
  | { type: "dimension"; kind: "length" | "radius"; entity: string; value: number }
  | { type: "dimension"; kind: "distance" | "distance_x" | "distance_y"; a: SketchPointRef; b: SketchPointRef; value: number }
  | { type: "fix"; point: SketchPointRef; value: Point2 }
  | { type: "fix"; entity: string; value?: number[] };

export interface ConstrainedSketch {
  entities: ConstrainedSketchEntity[];
  constraints: SketchConstraint[];
  regions?: Array<{ outer: string[] | string; holes: Array<string[] | string> }>;
}

export type SketchDrag =
  | { point: SketchPointRef; value: Point2 }
  | { entity: string; radius: number };

export interface SketchSolveResult {
  status: "fully_constrained" | "under_constrained";
  degrees_of_freedom: number;
  constraint_rank: number;
  residual_count: number;
  redundant_constraints: number;
  max_residual: number;
  entities: ConstrainedSketchEntity[];
}

export interface ConstrainedSketchExtrudeArgs {
  sketch: ConstrainedSketch;
  drag?: SketchDrag;
  plane: "XY" | "XZ" | "YZ";
  depth: number;
  result_id?: string;
  name?: string;
}

export interface RevolveArgs {
  profile: SketchProfile;
  plane: "XY" | "XZ" | "YZ";
  axis: RevolveAxis;
  angle: number;
  result_id?: string;
  name?: string;
}

export interface SweepArgs {
  section: SweepSection;
  path: SweepPath;
  frenet?: boolean;
  result_id?: string;
  name?: string;
}

export interface LoftArgs {
  sections: LoftSection[];
  ruled?: boolean;
  result_id?: string;
  name?: string;
}

export interface ShellArgs {
  outer_radius: number;
  height: number;
  wall: number;
  bottom: number;
  result_id?: string;
  name?: string;
}

export interface DraftPrismArgs {
  width: number;
  depth: number;
  height: number;
  angle: number;
  result_id?: string;
  name?: string;
}

export interface RibArgs {
  base_length: number;
  base_width: number;
  base_thickness: number;
  rib_length: number;
  rib_height: number;
  rib_width: number;
  overlap: number;
  result_id?: string;
  name?: string;
}

export type FitFixtureId = "nut_m5" | "bearing_608" | "heat_insert_m3";
export type FitClearanceMode = "radial" | "diametral" | "one_sided";

export interface FitPocketArgs {
  fixture_id: FitFixtureId;
  fixture_version: "1";
  body_length: number;
  body_width: number;
  body_height: number;
  clearance: number;
  clearance_mode: FitClearanceMode;
  pocket_depth?: number;
  result_id?: string;
  name?: string;
}

export interface VectorExtrudeArgs {
  path: string;
  format: "svg" | "dxf";
  height: number;
  unit_scale?: number;
  result_id?: string;
  name?: string;
}

export interface TextReliefArgs {
  text: string;
  font_size: number;
  relief_height: number;
  body_length: number;
  body_width: number;
  body_height: number;
  mode: "add" | "cut";
  result_id?: string;
  name?: string;
}

export interface ThreadPairArgs {
  profile_version: "metric-60-v1";
  major_diameter: number;
  pitch: number;
  length: number;
  hand: "right" | "left";
  starts: 1;
  clearance: number;
  nut_height: number;
  nut_across_flats: number;
  result_id?: string;
  name?: string;
}

export interface ClearanceCalibrationArgs {
  values: number[];
  nominal_diameter: number;
  coupon_length: number;
  coupon_width: number;
  thickness: number;
  spacing: number;
  font_size: number;
  label_height: number;
  profile_name?: string;
  result_id?: string;
  name?: string;
}

export interface SplitConnectorPairArgs {
  length: number;
  width: number;
  height: number;
  pin_radius: number;
  pin_length: number;
  radial_clearance: number;
  print_separation: number;
  result_id?: string;
  name?: string;
}

export type EdgeFeatureKind = "fillet" | "chamfer";

export type FaceAxis = "x" | "y" | "z";

export interface FaceFeatureRef {
  kind: "outer_planar";
  axis: FaceAxis;
  side: -1 | 1;
  anchor: [number, number];
  selected_area: number;
}

export interface FaceOffsetRef {
  kind: "planar";
  solid_index: number;
  center: Point3;
  normal: Point3;
  area: number;
}

export interface FaceOffsetArgs {
  target_id: string;
  face_ref: FaceOffsetRef;
  distance: number;
}

export type FaceProfileKind = "rectangle" | "circle" | "ring" | "slot";

export interface FaceFeatureProfile {
  kind: FaceProfileKind;
  center: [number, number];
  width?: number;
  height?: number;
  diameter?: number;
  outer_diameter?: number;
  inner_diameter?: number;
  length?: number;
}

export interface FaceFeatureArgs {
  target_id: string;
  mode: "add" | "cut";
  face_ref: FaceFeatureRef;
  profile: FaceFeatureProfile;
  depth: number | "through";
}

export interface FaceDomeArgs {
  target_id: string;
  mode: "add" | "cut";
  face_ref: FaceFeatureRef;
  center: [number, number];
  diameter: number;
  height: number;
}

export interface SheetBendArgs {
  target_id: string;
  face_ref: FaceFeatureRef;
  bend_axis: "x" | "y";
  position: number;
  angle: number;
  inside_radius: number;
  moving_side: -1 | 1;
  direction: -1 | 1;
}

export interface PartDef {
  part_id: string;
  name: string;
  template: string;
  params: Record<string, number>;
}

export interface PartStats {
  part_id: string;
  parametric_resize?: boolean;
  size_constraint?: "free" | "radial" | "uniform";
  bbox?: number[];
  name: string;
  volume: number | null;
  solid_count: number;
}

export interface DocStats {
  volume: number | null;
  solid_count: number;
  face_count: number | null;
  bbox: [number, number, number, number, number, number] | null;
  bbox_mesh?: number[];
  triangle_count?: number | null;
  is_valid: boolean;
  edges?: EdgeRef[];
  hole_centers?: [number, number][];
  case_volume?: number;
  lid_volume?: number;
  intersection_volume?: number;
  parts?: PartStats[];
  mesh_mode?: boolean;
  mesh_diagnostics?: {
    watertight: boolean;
    winding_consistent: boolean;
    boundary_edges: number;
    non_manifold_edges: number;
    degenerate_triangles: number;
    components: number;
    euler_number: number;
    self_intersection: "unknown";
    self_intersection_detail: string;
  };
  mesh_history?: Array<Record<string, unknown>>;
}

export interface DocState {
  doc_id?: string | number;
  document_instance_id?: string | number;
  revision: number;
  dirty: boolean;
  path: string | null;
  slot: "main" | "tutorial";
  template?: string | null;
  params: Record<string, number>;
  parts?: PartDef[];
  expressions: Record<string, string>;
  operations?: Operation[];
  stats: DocStats | null;
  error: GeoError | null;
  can_undo: boolean;
  can_redo: boolean;
  history_len?: number;
  history_index?: number;
}

export interface FaceRange {
  face_index: number;
  tri_start: number;
  tri_count: number;
  solid_index?: number;
  face_ref?: FaceOffsetRef | null;
  surface_ref?: SurfaceRef | null;
  feature_index?: number | null;
}

export interface SurfaceRef {
  kind: "plane" | "cylinder";
  center: Point3;
  direction: Point3;
  area: number;
  origin?: Point3;
  radius?: number;
}

export interface DimensionBindings {
  u?: { edge: "min" | "max"; offset: number };
  v?: { edge: "min" | "max"; offset: number };
  equal_diameter?: number;
}

export interface MeshData {
  vertex_count: number;
  triangle_count: number;
  positions: number[] | Float32Array;
  indices: number[] | Uint32Array;
  face_ranges: FaceRange[];
}

export interface PerformanceConfig {
  enabled: boolean;
  mode: "startup" | "workload" | string;
  project_path?: string | null;
  duration_ms: number;
}

export interface NativeE2eConfig {
  enabled: boolean;
  mode: "ai-http-cancel" | "ai-cad-cancel" | string;
  cancel_delay_ms: number;
}

export interface ExportResult {
  path: string;
  bytes: number;
  format?: string;
  linear_deflection?: number;
  stats: DocStats;
}

export interface MeshResource {
  path: string;
  bytes: number;
  sha256: string;
  vertex_count: number;
  triangle_count: number;
  face_ranges: FaceRange[];
}

export type MeshResourceMetadata = Omit<MeshResource, "path">;

export interface ImportResult {
  stats: DocStats;
  mesh: MeshResource;
  mode: "brep" | "mesh";
  document?: DocState;
}

export interface ImageReliefSettings {
  path: string;
  model: "heightmap-luminance-v1";
  seed: number;
  width_mm: number;
  relief_height: number;
  base_thickness: number;
  samples: number;
  noise_strength: number;
  invert: boolean;
}

export interface ImageReliefPreview {
  stats: DocStats;
  mesh: MeshResource;
  source_sha256: string;
  settings_sha256: string;
  settings_key?: string;
}

export interface PrintCheck {
  id: string;
  title: string;
  status: "pass" | "fail" | "unknown";
  detail?: string;
  issues?: Array<{ solid_index: number; face_local_index: number; point: Point3; thickness: number }>;
}

export interface PrintCheckResult {
  checks: PrintCheck[];
}

export interface AiProviderInfo {
  provider: "disabled" | "ollama" | "openai" | "scripted";
  available: boolean;
  scripted: boolean;
  model: string;
  base_url: string;
  has_api_key: boolean;
  secret_storage: "system" | "environment" | "session";
  local_endpoint: boolean;
  capabilities: {
    structured_output: boolean;
    json_object: boolean;
    tools: boolean;
    images: boolean;
    context_limit: number;
  };
}

export interface AiProviderConfig {
  provider: "disabled" | "ollama" | "openai";
  base_url: string;
  model: string;
  api_key?: string;
  clear_api_key?: boolean;
}

export interface AiConnectionTest {
  ok: boolean;
  message: string;
  model_found: boolean;
  models?: string[];
}

export interface AiOperation {
  command_id: "part.create.from_template" | "parameter.set" | "op.fillet";
  target_id: string | null;
  parameters: Record<string, unknown>;
}

export interface AiPlan {
  schema_version: 1;
  document_id: string | number;
  document_instance_id: string | number;
  base_revision: number;
  units: "mm";
  assumptions: string[];
  questions: string[];
  operations: AiOperation[];
  summary: string;
}

export interface AiPreview {
  mode: "preview";
  stats: DocStats | null;
  error: GeoError | null;
  parts: PartDef[];
  plan_hash: string;
  base_revision: number;
  document_instance_id: string | number;
}

export interface AiPlanResponse {
  plan: AiPlan;
  preview: AiPreview | null;
  plan_hash: string;
  action_id: string;
}

export interface CommandDef {
  command_id: string;
  title: string;
  help_id: string;
  shortcut: string | null;
  availability:
    | "always"
    | "requires_document"
    | "requires_body"
    | "requires_two_bodies"
    | "requires_undo"
    | "requires_redo"
    | "requires_ai";
  disabled_reason?: string;
  params: { name: string; unit?: string; min?: number; desc: string }[];
}

export interface TemplateParam {
  name: string;
  label: string;
  unit: string;
  min?: number;
  default: number;
}

export interface TemplateDef {
  template_id: string;
  kind?: "primitive" | "preset";
  title: string;
  command_id: string;
  help_id: string;
  params: TemplateParam[];
}

export interface HelpArticle {
  help_id: string;
  title: string;
  synonyms: string[];
  commands: string[];
  related: string[];
  body_markdown: string;
}

export interface HelpIndex {
  articles: HelpArticle[];
}

export interface LessonCheck {
  type: string;
  command_id?: string;
  template?: string;
  params?: Record<string, number>;
  hole_centers_abs_x?: number;
  op?: string;
  radius?: number;
  code?: string;
  id?: string;
  status?: string;
  mode?: string;
  format?: string;
  formats?: string[];
  normal?: Point3;
  distance?: number;
  nonzero_translate?: boolean;
  bbox_size?: Point3;
  bbox?: [number, number, number, number, number, number];
  volume?: number;
  solid_count?: number;
  mesh_mode?: boolean;
  boundary_edges?: number;
  degrees_of_freedom?: number;
  preview?: boolean;
  same_saved_path?: boolean;
  required_check?: { id: string; status: string };
}

export interface LessonStep {
  id: string;
  text: string;
  check: LessonCheck;
}

export interface Lesson {
  content_version?: number;
  lesson_id: string;
  title: string;
  goal: string;
  skills: string[];
  duration_min: number;
  steps: LessonStep[];
}

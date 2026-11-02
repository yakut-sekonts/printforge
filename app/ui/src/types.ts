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
}

export interface Operation {
  op: string;
  radius?: number;
  distance?: number;
  edge_ref?: EdgeRef;
  target_id?: string;
  mode?: "add" | "cut";
  face_ref?: FaceFeatureRef;
  profile?: FaceFeatureProfile;
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
  name: string;
  volume: number;
  solid_count: number;
}

export interface DocStats {
  volume: number;
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
}

export interface MeshData {
  vertex_count: number;
  triangle_count: number;
  positions: number[];
  indices: number[];
  face_ranges: FaceRange[];
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
  face_ranges: { face_index: number; solid_index?: number; tri_start: number; tri_count: number }[];
}

export interface ImportResult {
  stats: DocStats;
  mesh: MeshResource;
  mode: "brep" | "mesh";
}

export interface PrintCheck {
  id: string;
  title: string;
  status: "pass" | "fail" | "unknown";
  detail?: string;
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
}

export interface LessonStep {
  id: string;
  text: string;
  check: LessonCheck;
}

export interface Lesson {
  lesson_id: string;
  title: string;
  goal: string;
  skills: string[];
  duration_min: number;
  steps: LessonStep[];
}

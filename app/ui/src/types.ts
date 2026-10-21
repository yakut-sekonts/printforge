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
  edge_ref?: EdgeRef;
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
  face_count: number;
  bbox: [number, number, number, number, number, number];
  is_valid: boolean;
  edges?: EdgeRef[];
  hole_centers?: [number, number][];
  case_volume?: number;
  lid_volume?: number;
  intersection_volume?: number;
  parts?: PartStats[];
}

export interface DocState {
  doc_id?: string;
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

export interface ImportResult {
  stats: DocStats;
  mesh: MeshData;
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

export interface CommandDef {
  command_id: string;
  title: string;
  help_id: string;
  shortcut: string | null;
  availability: "always" | "requires_document" | "requires_body" | "requires_undo" | "requires_redo";
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

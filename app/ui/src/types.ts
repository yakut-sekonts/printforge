export interface GeoError {
  code: string;
  message: string;
  detail?: string;
}

export interface DocStats {
  volume: number;
  solid_count: number;
  face_count: number;
  bbox: [number, number, number, number, number, number];
  hole_centers: [number, number][];
  is_valid: boolean;
}

export interface DocState {
  revision: number;
  dirty: boolean;
  path: string | null;
  slot: "main" | "tutorial";
  params: Record<string, number>;
  expressions: Record<string, string>;
  stats: DocStats | null;
  error: GeoError | null;
  can_undo: boolean;
  can_redo: boolean;
  history_len: number;
  history_index: number;
  doc_id: string | number;
}

export interface FaceRange {
  face_index: number;
  tri_start: number;
  tri_count: number;
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
  linear_deflection: number;
  stats: DocStats;
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
  params?: Record<string, number>;
  hole_centers_abs_x?: number;
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

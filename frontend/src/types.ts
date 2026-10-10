export interface User {
  id: string;
  name: string;
  role: string;
  email: string;
  initials: string;
}

// Backend Document Read Model
export interface DocumentRead {
  doc_id: number;
  user_id?: number;
  organization_id?: number;
  title: string;
  structure_status: 'pending' | 'processing' | 'done' | 'partial' | 'failed';
  created_at?: string;
}

// Backend Structured Record (from GET /api/v1/document/{id}/structure)
export interface StructuredRecord {
  id: number;
  doc_title?: string;
  kind: 'title' | 'preamble' | 'article';
  number?: number | null;
  number_raw?: string | null;
  chapter?: any;
  amends_law?: any;
  amends_article?: any;
  text: string;
}

// Backend Relation Item (from workflow status completed and history detail)
export type RelationCategory = 'مشابه' | 'متناقض';
export type RelationTypeTag =
  | 'تکرار مقرراتی'
  | 'اقتباس'
  | 'تکمیل'
  | 'تخصیص'
  | 'تعارض'
  | 'نسخ صریح'
  | 'نسخ ضمنی'
  | 'ابهام تفسیری'
  | 'ناسازگاری'
  | string;

export interface BackendRelation {
  source_id: number;
  target_id: number;
  relation: RelationCategory;
  relation_type: RelationTypeTag;
  explanation: string;
  confidence: number;
}

// Workflow Status Types
export type WorkflowStep =
  | 'load_context'
  | 'load_vector_stores'
  | 'retrieve_candidates'
  | 'analyze_with_llm';

export interface WorkflowStatusResponse {
  run_id: string;
  status: 'queued' | 'running' | 'failed' | 'completed' | 'not_found';
  step?: WorkflowStep | string;
  error?: string;
  analysis_id?: number | null;
  count?: number;
  relations?: BackendRelation[];
}

// History List Item (from GET /analyze/history)
export interface HistoryListItem {
  analysis_id: number;
  document_a_id?: number;
  document_b_id?: number;
  created_at: string;
  // If backend returns populated doc objects as well
  doc_a?: { doc_id: number; title: string };
  doc_b?: { doc_id: number; title: string };
}

// History Detail (from GET /analyze/history/{analysis_id})
export interface HistoryDetailResponse {
  analysis_id: number;
  created_at: string;
  document_a_id?: number;
  document_b_id?: number;
  doc_a?: { doc_id: number; title?: string; structure?: StructuredRecord[] };
  doc_b?: { doc_id: number; title?: string; structure?: StructuredRecord[] };
  count?: number;
  relations?: BackendRelation[];
  // If backend returns root structure or flat relations
  [key: string]: any;
}

// Frontend UI State Models
export interface DocumentInfo {
  id: string;
  docId?: number;
  title: string;
  fileName: string;
  tag: string;
  date: string;
  pageCount?: number;
  fileSize?: string;
  status: 'ready' | 'pending' | 'processing' | 'failed';
  rawFile?: File;
  structureStatus?: 'pending' | 'processing' | 'done' | 'partial' | 'failed';
}

export interface Clause {
  id: string;
  backendId?: number;
  clauseId: string;
  title: string;
  content: string[];
  kind?: 'title' | 'preamble' | 'article';
  highlightSnippet?: string;
  relationType?: 'conflict' | 'similarity';
  relatedClauseTitle?: string;
  relationCount?: number;
  relationSummaries?: string[];
}

export interface Relation {
  id: string;
  key: string;
  title: string;
  category: 'conflict' | 'similarity';
  relation: string;
  type: string;
  summary?: string;
  reasoning: string;
  confidence?: number;
  sourceId?: number;
  targetId?: number;
  targetDocA?: string;
  targetDocB?: string;
}

export interface AnalysisStep {
  id: number;
  key?: WorkflowStep | string;
  title: string;
  status: 'completed' | 'in_progress' | 'queued' | 'stopped';
  detail?: string;
}

export interface HistoryItem {
  id: string;
  analysisId?: number;
  displayNumber?: number;
  docAId?: number;
  docBId?: number;
  title: string;
  timeAgo: string;
  formattedDate?: string;
  doc1Name: string;
  doc2Name: string;
  relationsCount: number;
}

export type AppScreen = 'login' | 'upload' | 'processing' | 'error' | 'compare';

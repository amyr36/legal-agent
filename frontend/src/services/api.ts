// Service Layer for Legal Agent Backend API
// Base URL: http://localhost:8080
// Auth prefix: /api/v1/auth
// Document prefix: /api/v1/document
// Analyze prefix: /analyze

import {
  User,
  DocumentInfo,
  Clause,
  Relation,
  AnalysisStep,
  HistoryItem,
  DocumentRead,
  StructuredRecord,
  WorkflowStatusResponse,
  WorkflowStep,
  BackendRelation,
  HistoryListItem,
  HistoryDetailResponse,
} from '../types';

// API Base URL resolution (stored in localStorage or env or default to 8080)
const STORAGE_KEY_API_URL = 'legal_agent_api_base_url';
const STORAGE_KEY_TOKEN = 'legal_agent_token';
const STORAGE_KEY_USER = 'legal_agent_user';

export const getApiBaseUrl = (): string => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem(STORAGE_KEY_API_URL);
    if (saved) {
      if (saved.includes('8000')) {
        const updated = saved.replace('8000', '8080');
        localStorage.setItem(STORAGE_KEY_API_URL, updated);
        return updated.replace(/\/+$/, '');
      }
      return saved.replace(/\/+$/, '');
    }
  }
  return (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8080';
};

export const setApiBaseUrl = (url: string) => {
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORAGE_KEY_API_URL, url.replace(/\/+$/, ''));
  }
};

// Auth Token Management
export const getAuthToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(STORAGE_KEY_TOKEN);
};

export const setAuthToken = (token: string) => {
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORAGE_KEY_TOKEN, token);
  }
};

export const removeAuthToken = () => {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(STORAGE_KEY_TOKEN);
    localStorage.removeItem(STORAGE_KEY_USER);
  }
};

// Unauthorized callback registry (redirects to login on 401)
let onUnauthorizedCallback: (() => void) | null = null;
export const registerUnauthorizedHandler = (callback: () => void) => {
  onUnauthorizedCallback = callback;
};

const handleUnauthorized = () => {
  removeAuthToken();
  if (onUnauthorizedCallback) {
    onUnauthorizedCallback();
  }
};

// Generic Fetch Wrapper
async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {},
  isMultipart = false
): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${endpoint}`;

  const headers: Record<string, string> = {};

  if (!isMultipart) {
    headers['Content-Type'] = 'application/json';
  }

  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // Merge headers
  if (options.headers) {
    Object.assign(headers, options.headers);
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    // 401 Unauthorized -> user token expired or invalid (30 min lifetime)
    if (response.status === 401) {
      handleUnauthorized();
      throw new Error('نشست کاربری شما منقضی شده است. لطفاً دوباره وارد شوید.');
    }

    // 204 No Content
    if (response.status === 204) {
      return {} as T;
    }

    if (!response.ok) {
      let errorMessage = `خطا در ارتباط با سرور (${response.status})`;
      try {
        const errorJson = await response.json();
        if (typeof errorJson.detail === 'string') {
          errorMessage = errorJson.detail;
        } else if (Array.isArray(errorJson.detail)) {
          errorMessage = errorJson.detail.map((d: any) => d.msg || d.loc?.join('.')).join(' ، ');
        } else if (errorJson.error) {
          errorMessage = errorJson.error;
        }
      } catch {
        // failed to parse json error, use status text
        if (response.statusText) errorMessage = response.statusText;
      }
      throw new Error(errorMessage);
    }

    return (await response.json()) as T;
  } catch (error: any) {
    // Check if network failed completely (server down / CORS / connection refused)
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      throw new Error(
        `امکان برقراری ارتباط با سرور در ${baseUrl} وجود ندارد. لطفاً از روشن بودن سرور بک‌اند (پورت 8080) اطمینان حاصل کنید.`
      );
    }
    throw error;
  }
}

// ==========================================
// 1. System Endpoints
// ==========================================
export const SystemApi = {
  async getRoot(): Promise<{ name: string; status: string }> {
    return apiFetch<{ name: string; status: string }>('/');
  },

  async getHealth(): Promise<{ status: string; database?: string }> {
    return apiFetch<{ status: string; database?: string }>('/health');
  },
};

// ==========================================
// 2. Auth Endpoints (/api/v1/auth)
// ==========================================
export const AuthApi = {
  async login(
    username: string,
    password: string
  ): Promise<{ access_token: string; token_type: string }> {
    const res = await apiFetch<{ access_token: string; token_type: string }>(
      '/api/v1/auth/login',
      {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }
    );
    setAuthToken(res.access_token);
    return res;
  },

  async register(
    username: string,
    phoneNumber: string,
    password: string,
    roleId = 1
  ): Promise<{ access_token: string; token_type: string }> {
    const res = await apiFetch<{ access_token: string; token_type: string }>(
      '/api/v1/auth/register',
      {
        method: 'POST',
        body: JSON.stringify({
          username,
          phone_number: phoneNumber,
          password,
          role_id: roleId,
        }),
      }
    );
    setAuthToken(res.access_token);
    return res;
  },

  logout() {
    removeAuthToken();
  },
};

// ==========================================
// 3. Document Endpoints (/api/v1/document)
// ==========================================
export const DocumentApi = {
  // POST /api/v1/document/ (trailing slash required!)
  async uploadDocument(
    file: File,
    title: string,
    organizationId = 1
  ): Promise<DocumentRead> {
    if (file.size > 300 * 1024) {
      throw new Error('حجم فایل PDF حداکثر باید ۳۰۰ کیلوبایت باشد.');
    }
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      throw new Error('فقط فایل با فرمت PDF مجاز است.');
    }

    const formData = new FormData();
    formData.append('title', title);
    formData.append('organization_id', String(organizationId));
    formData.append('file', file);

    return apiFetch<DocumentRead>(
      '/api/v1/document/',
      {
        method: 'POST',
        body: formData,
      },
      true // isMultipart
    );
  },

  async getDocuments(
    skip = 0,
    limit = 100,
    organizationId?: number
  ): Promise<DocumentRead[]> {
    let url = `/api/v1/document/?skip=${skip}&limit=${limit}`;
    if (organizationId) {
      url += `&organization_id=${organizationId}`;
    }
    return apiFetch<DocumentRead[]>(url);
  },

  async getDocument(documentId: number): Promise<DocumentRead> {
    return apiFetch<DocumentRead>(`/api/v1/document/${documentId}`);
  },

  async updateDocument(
    documentId: number,
    data: { title?: string; organization_id?: number }
  ): Promise<DocumentRead> {
    return apiFetch<DocumentRead>(`/api/v1/document/${documentId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async deleteDocument(documentId: number): Promise<void> {
    return apiFetch<void>(`/api/v1/document/${documentId}`, {
      method: 'DELETE',
    });
  },

  async getDocumentStructure(documentId: number): Promise<StructuredRecord[]> {
    return apiFetch<StructuredRecord[]>(`/api/v1/document/${documentId}/structure`);
  },

  // Helper: Poll document structure until done or explicit failure
  async pollStructureStatus(
    documentId: number,
    onProgress?: (status: string) => void,
    initialIntervalMs = 1500,
    maxTimeoutMs = 10 * 60 * 1000 // 10 minutes safety cap
  ): Promise<DocumentRead> {
    const startTime = Date.now();
    let currentInterval = initialIntervalMs;
    while (Date.now() - startTime < maxTimeoutMs) {
      const doc = await this.getDocument(documentId);
      if (onProgress) onProgress(doc.structure_status);

      if (doc.structure_status === 'done') {
        return doc;
      }
      if (doc.structure_status === 'failed' || (doc as any).structure_status === 'error') {
        throw new Error('استخراج و ساختاردهی سند با خطا مواجه شد.');
      }

      await new Promise((resolve) => setTimeout(resolve, currentInterval));
      // Progressive backoff: start from 1.5s up to 5s
      currentInterval = Math.min(5000, currentInterval + 500);
    }
    throw new Error('زمان انتظار برای ساختاردهی سند به پایان رسید (timeout).');
  },
};

// ==========================================
// 4. Analyze Workflow Endpoints (/analyze)
// ==========================================
export const AnalyzeApi = {
  // POST /analyze/workflow/run
  async runWorkflow(docAId: number, docBId: number): Promise<{ run_id: string }> {
    if (docAId === docBId) {
      throw new Error('برای مقایسه باید دو سند متمایز انتخاب کنید.');
    }
    return apiFetch<{ run_id: string }>('/analyze/workflow/run', {
      method: 'POST',
      body: JSON.stringify({
        doc_a_id: docAId,
        doc_b_id: docBId,
      }),
    });
  },

  // GET /analyze/workflow/status?run_id=...
  async getWorkflowStatus(runId: string): Promise<WorkflowStatusResponse> {
    return apiFetch<WorkflowStatusResponse>(
      `/analyze/workflow/status?run_id=${encodeURIComponent(runId)}`
    );
  },

  // POST /analyze/workflow/resume?run_id=...
  async resumeWorkflow(runId: string): Promise<{ run_id: string }> {
    return apiFetch<{ run_id: string }>(
      `/analyze/workflow/resume?run_id=${encodeURIComponent(runId)}`,
      {
        method: 'POST',
      }
    );
  },
};

// ==========================================
// 4-B. History Endpoints (/analyze/history)
// ==========================================
export const HistoryApi = {
  // GET /analyze/history
  async getHistory(skip = 0, limit = 50): Promise<HistoryListItem[]> {
    return apiFetch<HistoryListItem[]>(`/analyze/history?skip=${skip}&limit=${limit}`);
  },

  // GET /analyze/history/{analysis_id}
  async getHistoryDetail(analysisId: number): Promise<HistoryDetailResponse> {
    return apiFetch<HistoryDetailResponse>(`/analyze/history/${analysisId}`);
  },
};

// ==========================================
// Model Adapters & Data Transformers
// ==========================================
export function transformStructureToClauses(records: StructuredRecord[]): Clause[] {
  if (!records || !Array.isArray(records)) return [];

  return records.map((rec) => {
    let title = '';
    if (rec.number_raw) {
      title = rec.number_raw;
      if (rec.doc_title && rec.doc_title !== rec.number_raw) {
        title += `: ${rec.doc_title}`;
      }
    } else if (rec.kind === 'preamble') {
      title = 'مقدمه سند';
    } else if (rec.kind === 'title') {
      title = rec.doc_title || 'عنوان مقرره';
    } else {
      title = rec.doc_title || `بخش ${rec.id}`;
    }

    return {
      id: `clause_record_${rec.id}`,
      backendId: rec.id,
      clauseId: `rec_${rec.id}`,
      title,
      content: [rec.text],
      kind: rec.kind,
    };
  });
}

export function transformBackendRelations(
  relations: BackendRelation[],
  clausesDocA: Clause[] = [],
  clausesDocB: Clause[] = []
): Record<string, Relation> {
  const result: Record<string, Relation> = {};

  if (!relations || !Array.isArray(relations)) return result;

  relations.forEach((rel, index) => {
    const key = `rel_${rel.source_id}_${rel.target_id}_${index}`;
    const category = rel.relation === 'متناقض' ? 'conflict' : 'similarity';

    // Find referenced clauses
    const clauseA = clausesDocA.find((c) => c.backendId === rel.source_id);
    const clauseB = clausesDocB.find((c) => c.backendId === rel.target_id);

    const titleA = clauseA?.title || `بند ${rel.source_id}`;
    const titleB = clauseB?.title || `بند ${rel.target_id}`;

    result[key] = {
      id: `rel_${index}`,
      key,
      title: `${titleA} ⇄ ${titleB}`,
      category,
      relation: rel.relation,
      type: rel.relation_type,
      reasoning: rel.explanation,
      confidence: rel.confidence,
      sourceId: rel.source_id,
      targetId: rel.target_id,
      targetDocA: clauseA?.id || `clause_record_${rel.source_id}`,
      targetDocB: clauseB?.id || `clause_record_${rel.target_id}`,
    };
  });

  return result;
}

// ==========================================
// Document Compilation & Cross-Analysis Engine
// Compiles raw/structured document text in background
// and directly projects analysis results onto the compiled documents
// ==========================================
export function compileClausesWithRelations(
  clausesA: Clause[],
  clausesB: Clause[],
  relationsInput: BackendRelation[] | Record<string, Relation>
): {
  clausesDoc1: Clause[];
  clausesDoc2: Clause[];
  relations: Record<string, Relation>;
} {
  const docAClauses: Clause[] = clausesA.map((c) => ({
    ...c,
    content: [...c.content],
    relationSummaries: [],
    relationCount: 0,
  }));
  const docBClauses: Clause[] = clausesB.map((c) => ({
    ...c,
    content: [...c.content],
    relationSummaries: [],
    relationCount: 0,
  }));

  const compiledRelations: Record<string, Relation> = {};

  if (Array.isArray(relationsInput)) {
    // BackendRelation[] array
    relationsInput.forEach((rel, index) => {
      const key = `rel_${rel.source_id}_${rel.target_id}_${index}`;
      const category: 'conflict' | 'similarity' =
        rel.relation === 'متناقض' ? 'conflict' : 'similarity';

      let clauseA = docAClauses.find(
        (c) =>
          c.backendId === rel.source_id ||
          c.id === `clause_record_${rel.source_id}` ||
          c.clauseId === `rec_${rel.source_id}` ||
          c.clauseId === `art${rel.source_id}`
      );
      let clauseB = docBClauses.find(
        (c) =>
          c.backendId === rel.target_id ||
          c.id === `clause_record_${rel.target_id}` ||
          c.clauseId === `rec_${rel.target_id}` ||
          c.clauseId === `art${rel.target_id}`
      );

      // Fallback matching if exact IDs differ in mock mode
      if (!clauseA && docAClauses.length > 0) {
        const idx = Math.abs(rel.source_id || index) % docAClauses.length;
        clauseA = docAClauses[idx];
      }
      if (!clauseB && docBClauses.length > 0) {
        const idx = Math.abs(rel.target_id || index) % docBClauses.length;
        clauseB = docBClauses[idx];
      }

      const titleA = clauseA?.title || `بند ${rel.source_id}`;
      const titleB = clauseB?.title || `بند ${rel.target_id}`;

      const targetDocA = clauseA ? clauseA.id : `clause_record_${rel.source_id}`;
      const targetDocB = clauseB ? clauseB.id : `clause_record_${rel.target_id}`;

      compiledRelations[key] = {
        id: `rel_${index}`,
        key,
        title: `${titleA} ⇄ ${titleB}`,
        category,
        relation: rel.relation,
        type: rel.relation_type,
        reasoning: rel.explanation,
        confidence: rel.confidence,
        sourceId: rel.source_id,
        targetId: rel.target_id,
        targetDocA,
        targetDocB,
      };

      // Project results onto compiled Clause A
      if (clauseA) {
        if (!clauseA.relationType || category === 'conflict') {
          clauseA.relationType = category;
        }
        clauseA.relatedClauseTitle = titleB;
        clauseA.relationCount = (clauseA.relationCount || 0) + 1;
        clauseA.relationSummaries = [
          ...(clauseA.relationSummaries || []),
          `${rel.relation}: ${rel.relation_type}`,
        ];
      }

      // Project results onto compiled Clause B
      if (clauseB) {
        if (!clauseB.relationType || category === 'conflict') {
          clauseB.relationType = category;
        }
        clauseB.relatedClauseTitle = titleA;
        clauseB.relationCount = (clauseB.relationCount || 0) + 1;
        clauseB.relationSummaries = [
          ...(clauseB.relationSummaries || []),
          `${rel.relation}: ${rel.relation_type}`,
        ];
      }
    });
  } else if (relationsInput && typeof relationsInput === 'object') {
    // Record<string, Relation> map
    Object.entries(relationsInput).forEach(([key, rel]) => {
      compiledRelations[key] = { ...rel };

      const clauseA = docAClauses.find(
        (c) =>
          c.id === rel.targetDocA ||
          c.clauseId === rel.key ||
          (c.backendId !== undefined && c.backendId === rel.sourceId)
      );
      const clauseB = docBClauses.find(
        (c) =>
          c.id === rel.targetDocB ||
          c.clauseId === rel.key ||
          (c.backendId !== undefined && c.backendId === rel.targetId)
      );

      if (clauseA) {
        if (!clauseA.relationType || rel.category === 'conflict') {
          clauseA.relationType = rel.category;
        }
        clauseA.relatedClauseTitle = clauseB?.title || rel.title;
        clauseA.relationCount = (clauseA.relationCount || 0) + 1;
        clauseA.relationSummaries = [
          ...(clauseA.relationSummaries || []),
          `${rel.relation || rel.category}: ${rel.type}`,
        ];
      }

      if (clauseB) {
        if (!clauseB.relationType || rel.category === 'conflict') {
          clauseB.relationType = rel.category;
        }
        clauseB.relatedClauseTitle = clauseA?.title || rel.title;
        clauseB.relationCount = (clauseB.relationCount || 0) + 1;
        clauseB.relationSummaries = [
          ...(clauseB.relationSummaries || []),
          `${rel.relation || rel.category}: ${rel.type}`,
        ];
      }
    });
  }

  return {
    clausesDoc1: docAClauses,
    clausesDoc2: docBClauses,
    relations: compiledRelations,
  };
}

// Background Document Compiler
export async function compileDocumentsWithAnalysis(params: {
  docAId?: number;
  docBId?: number;
  analysisId?: number | null;
  relations: BackendRelation[];
  fallbackClausesDocA?: Clause[];
  fallbackClausesDocB?: Clause[];
  onProgress?: (message: string, percent?: number) => void;
}): Promise<{
  clausesDoc1: Clause[];
  clausesDoc2: Clause[];
  relations: Record<string, Relation>;
  relationsCount: number;
  conflictsCount: number;
  similaritiesCount: number;
}> {
  // 1. Fetch text and structure of both documents directly using docAId and docBId
  if (params.onProgress) {
    params.onProgress('در حال دریافت متن و ساختار دو سند از سرور...', 93);
  }

  let struct1: StructuredRecord[] = [];
  let struct2: StructuredRecord[] = [];

  // Directly fetch structures from /api/v1/document/{id}/structure
  if (params.docAId) {
    try {
      struct1 = await DocumentApi.getDocumentStructure(params.docAId);
    } catch (e) {
      console.warn('Could not fetch structure for doc A:', e);
    }
  }
  if (params.docBId) {
    try {
      struct2 = await DocumentApi.getDocumentStructure(params.docBId);
    } catch (e) {
      console.warn('Could not fetch structure for doc B:', e);
    }
  }

  // Fallback to history detail if needed
  if ((!struct1.length || !struct2.length) && params.analysisId) {
    try {
      const detail = await HistoryApi.getHistoryDetail(params.analysisId);
      if (!struct1.length && detail.doc_a?.structure?.length) struct1 = detail.doc_a.structure;
      if (!struct2.length && detail.doc_b?.structure?.length) struct2 = detail.doc_b.structure;
    } catch (e) {
      console.warn('Could not fetch structures from history detail:', e);
    }
  }

  // 2. Compile document structure and text
  if (params.onProgress) {
    params.onProgress('در حال کامپایل متن اسناد و اعتبارسنجی ساختار مواد...', 96);
  }
  await new Promise((r) => setTimeout(r, 200));

  const baseClausesA = struct1.length
    ? transformStructureToClauses(struct1)
    : (params.fallbackClausesDocA || []);
  const baseClausesB = struct2.length
    ? transformStructureToClauses(struct2)
    : (params.fallbackClausesDocB || []);

  // 3. Project analysis results & relations onto compiled documents
  if (params.onProgress) {
    params.onProgress('در حال اعمال نتایج تحلیل و هایلایت‌ها بر روی اسناد کامپایل‌شده...', 98);
  }
  await new Promise((r) => setTimeout(r, 200));

  const compiled = compileClausesWithRelations(
    baseClausesA,
    baseClausesB,
    params.relations
  );

  const allRelations = Object.values(compiled.relations);
  const conflictsCount = allRelations.filter((r) => r.category === 'conflict').length;
  const similaritiesCount = allRelations.filter((r) => r.category === 'similarity').length;

  if (params.onProgress) {
    params.onProgress('اسناد کامپایل شدند و گزارش آماده نمایش است.', 100);
  }

  return {
    clausesDoc1: compiled.clausesDoc1,
    clausesDoc2: compiled.clausesDoc2,
    relations: compiled.relations,
    relationsCount: allRelations.length,
    conflictsCount,
    similaritiesCount,
  };
}

// Convert relative ISO time to Persian friendly string
export function formatPersianTimeAgo(isoString?: string): string {
  if (!isoString) return 'اخیراً';
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 5) return 'چند لحظه پیش';
    if (diffMins < 60) return `${diffMins} دقیقه پیش`;
    if (diffHours < 24) return `${diffHours} ساعت پیش`;
    if (diffDays === 1) return 'دیروز';
    if (diffDays < 7) return `${diffDays} روز پیش`;
    return date.toLocaleDateString('fa-IR');
  } catch {
    return 'اخیراً';
  }
}

// Convert ISO time to exact Persian Date string (e.g. ۱۴۰۵/۰۷/۱۹)
export function formatPersianDate(isoString?: string): string {
  if (!isoString) return '';
  try {
    const date = new Date(isoString);
    return date.toLocaleDateString('fa-IR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return isoString;
  }
}

// ==========================================
// Compatibility Mock Data & Default Service
// (Available as fallback when backend is offline)
// ==========================================
export const CURRENT_USER: User = {
  id: 'usr_1',
  name: 'کارشناس حقوقی',
  role: 'تحلیلگر حقوقی',
  email: 'legal@example.com',
  initials: 'ک.ح',
};

export const MOCK_DOC_1: DocumentInfo = {
  id: 'doc_1',
  docId: 1,
  title: 'سند اول',
  fileName: 'قرارداد_مشارکت_۱.pdf',
  tag: 'نسخه مبنا',
  date: '۱۴۰۲/۰۶/۱۵',
  pageCount: 3,
  fileSize: '۲۸۰ کیلوبایت',
  status: 'ready',
};

export const MOCK_DOC_2: DocumentInfo = {
  id: 'doc_2',
  docId: 2,
  title: 'سند دوم',
  fileName: 'الحاقیه_تعدیل_سود_۲.pdf',
  tag: 'نسخه مؤخر',
  date: '۱۴۰۳/۰۴/۲۰',
  pageCount: 3,
  fileSize: '۲۵۰ کیلوبایت',
  status: 'ready',
};

export const MOCK_CLAUSES_DOC1: Clause[] = [
  {
    id: 'clauseA1',
    clauseId: 'art1',
    title: 'ماده ۱: طرفین و موضوع مشارکت',
    content: [
      'این قرارداد فیمابین شرکت سرمایه‌گذاری تابان عمران (شریک اول) و آقای دکتر کامران بهرامی به عنوان مالک عرصه (شریک دوم) با هدف احداث مجتمع مسکونی منعقد گردید.',
    ],
  },
  {
    id: 'clauseA2',
    clauseId: 'art2',
    title: 'ماده ۲: مشخصات عرصه و ارزش‌گذاری',
    relationType: 'similarity',
    content: [
      'عرصه مذکور به مساحت ۱۲۰۰ مترمربع به مبلغ توافقی طبق نظریه کارشناس رسمی دادگستری تقویم و به عنوان آورده اولیه مالک منظور گردید.',
    ],
  },
  {
    id: 'clauseA3',
    clauseId: 'art3',
    title: 'ماده ۳: تعهدات اجرایی',
    content: [
      'تأمین کلیه هزینه‌های پروانه ساختمانی، تخریب، طراحی، دستمزد عوامل اجرایی و تجهیز کامل کارگاه راساً بر عهده شریک اول خواهد بود.',
    ],
  },
  {
    id: 'highlightDocA',
    clauseId: 'art4',
    title: 'ماده ۴',
    relationType: 'conflict',
    content: [
      '۱-۴. تقسیم کل مساحت مفید احداثی و منافع حاصله به نسبت شصت درصد (۶۰٪) برای سرمایه‌گذار و چهل درصد (۴۰٪) برای مالک تثبیت و تسویه خواهد گردید.',
      '۲-۴. در صورت بروز هرگونه تأخیر ناموجه بیش از سه ماه در اجرای زمان‌بندی، شریک اول متعهد به پرداخت وجه التزام روزانه پنجاه میلیون ریال می‌باشد.',
    ],
  },
  {
    id: 'clauseA5',
    clauseId: 'art5',
    title: 'ماده ۵: برنامه زمان‌بندی اجرا',
    content: [
      'کل دوره عملیات اجرایی از تاریخ صدور جواز ساختمانی، حداکثر ۳۶ ماه شمسی تعیین می‌گردد و طرفین ملزم به رعایت مواعد پیشرفت فیزیکی هستند.',
    ],
  },
  {
    id: 'clauseA6',
    clauseId: 'art6',
    title: 'ماده ۶: نظارت فنی',
    content: [
      'مهندس ناظر مقیم منتخب از سوی سازمان نظام مهندسی ساختمان، مرجع داوری فنی در خصوص کیفیت اجرا و انطباق با نقشه‌های مصوب خواهد بود.',
    ],
  },
  {
    id: 'clauseA7',
    clauseId: 'art7',
    title: 'ماده ۷: حل اختلاف',
    relationType: 'conflict',
    content: [
      'کلیه اختلافات ناشی از تفسیر یا اجرای این قرارداد بدواً از طریق مذاکره و در صورت عدم حصول توافق، در مراجع ذیصلاح دادگستری تهران رسیدگی خواهد شد.',
    ],
  },
  {
    id: 'clauseA10',
    clauseId: 'art10',
    title: 'ماده ۱۰: فورس ماژور و شرایط اضطراری',
    relationType: 'similarity',
    content: [
      'حوادث قهریه و غیرقابل پیش‌بینی خارج از اراده طرفین مانع از اجرای تعهدات بوده و موجب تعلیق مهلت‌های قانونی می‌گردد.',
    ],
  },
];

export const MOCK_CLAUSES_DOC2: Clause[] = [
  {
    id: 'clauseB0',
    clauseId: 'art0_intro',
    title: 'مقدمه الحاقیه و قصد انشایی',
    content: [
      'پیرو قرارداد مشارکت در ساخت شماره ۱۱۰۴ مورخ ۱۴۰۲/۰۶/۱۵، طرفین با توجه به تغییر شاخص‌های اقتصادی و نوسانات نرخ مصالح ساختمانی با تراضی کامل مفاد زیر را به عنوان الحاقیه لازم‌الاجرا توافق نمودند.',
    ],
  },
  {
    id: 'clauseB1',
    clauseId: 'art1_add',
    title: 'بند ۱: تثبیت عرصه اولیه',
    relationType: 'similarity',
    content: [
      'مساحت و ارزش‌گذاری عرصه به مساحت ۱۲۰۰ مترمربع طبق بند ۲ قرارداد پایه بدون تغییر ابقا می‌گردد.',
    ],
  },
  {
    id: 'highlightDocB',
    clauseId: 'art2_ratio',
    title: 'بند ۲',
    relationType: 'conflict',
    content: [
      'طرفین توافق نمودند نسبت تقسیم واحدهای احداثی و قدرالسهم نهایی پروژه، به میزان پنجاه درصد (۵۰٪) برای هر یک از طرفین تعیین گردد. کلیه بندهای مغایر در ماده ۴ قرارداد اولیه کأن لم یکن تلقی می‌گردد.',
    ],
  },
  {
    id: 'clauseB3',
    clauseId: 'art3_delay',
    title: 'بند ۳: وجه التزام تعدیل‌شده',
    relationType: 'conflict',
    content: [
      'مبلغ خسارت تأخیر روزانه به مبلغ یکصد میلیون ریال افزایش یافته و شروع محاسبه از ماه دوم تأخیر خواهد بود.',
    ],
  },
  {
    id: 'clauseB4',
    clauseId: 'art4_exec',
    title: 'بند ۴: تعهدات تکمیلی سازنده',
    content: [
      'شریک اول موظف است حداکثر ظرف مدت ۴۵ روز از امضای این الحاقیه، بیمه‌نامه مسئولیت مدنی جامع پروژه را اخذ و تسلیم نماید.',
    ],
  },
  {
    id: 'clauseB5',
    clauseId: 'art5_arb',
    title: 'بند ۵: شرط داوری مستقل',
    relationType: 'conflict',
    content: [
      'ماده ۷ قرارداد پایه نسخ گردیده و هرگونه اختلاف ناشی از تفسیر این توافقنامه منحصراً به هیئت داوری مرکز داوری اتاق بازرگانی ارجاع می‌شود.',
    ],
  },
  {
    id: 'clauseB7',
    clauseId: 'art7_force',
    title: 'بند ۷: تداوم شرایط فورس ماژور',
    relationType: 'similarity',
    content: [
      'مفاد ماده ۱۰ قرارداد پایه در خصوص فورس ماژور و تعلیق با همان ضوابط به قوت خود باقی است.',
    ],
  },
];

export const MOCK_HISTORY: HistoryItem[] = [
  {
    id: 'hist_1',
    analysisId: 101,
    title: 'تحلیل قرارداد مشارکت و الحاقیه',
    timeAgo: 'دیروز',
    doc1Name: 'قرارداد_مشارکت_۱.pdf',
    doc2Name: 'الحاقیه_تعدیل_سود_۲.pdf',
    relationsCount: 4,
  },
  {
    id: 'hist_2',
    analysisId: 102,
    title: 'تحلیل مبایعه‌نامه و شروط داوری',
    timeAgo: '۳ روز پیش',
    doc1Name: 'مبایعه_نامه_اصلی.pdf',
    doc2Name: 'متمم_داوری_جدید.pdf',
    relationsCount: 3,
  },
];

export const MOCK_RELATIONS: Record<string, Relation> = {
  art4: {
    id: 'rel_1',
    key: 'art4',
    title: 'ماده ۴ و بند ۲ الحاقیه',
    category: 'conflict',
    relation: 'متناقض',
    type: 'تعارض در تعیین سهم‌الشرکه و وجه التزام',
    summary: 'تغییر نسبت تسهیم منافع از ۶۰/۴۰ به ۵۰/۵۰',
    reasoning:
      'در ماده ۴ قرارداد اولیه، نسبت تقسیم منافع به صورت ۶۰٪ سرمایه‌گذار و ۴۰٪ مالک توافق گردیده بود؛ اما در بند ۲ الحاقیه جدید، طرفین این نسبت را به بالمناصفه (۵۰٪ - ۵۰٪) تغییر داده‌اند که نسخ ضمنی بند اولیه محسوب می‌شود.',
    targetDocA: 'highlightDocA',
    targetDocB: 'highlightDocB',
  },
  art7: {
    id: 'rel_2',
    key: 'art7',
    title: 'ماده ۷ و بند الحاقی ۴',
    category: 'conflict',
    relation: 'متناقض',
    type: 'نسخ صریح مرجع حل اختلاف',
    summary: 'تغییر مرجع رسیدگی از محاکم عمومی دادگستری به داوری اتاق بازرگانی',
    reasoning:
      'ماده ۷ قرارداد پایه رسیدگی به اختلافات را در صلاحیت دادگاه‌های دادگستری تهران قرار داده بود، در حالی که در بند ۴ الحاقیه توافق شده است کلیه اختلافات منحصراً به هیئت داوری ارجاع گردد.',
    targetDocA: 'clauseA7',
    targetDocB: 'clauseB4',
  },
  art2: {
    id: 'rel_3',
    key: 'art2',
    title: 'ماده ۲ و بند الحاقی ۱',
    category: 'similarity',
    relation: 'مشابه',
    type: 'تکرار مقرراتی و تأیید عرصه',
    summary: 'تطابق مساحت عرصه و عدم تغییر کاربری',
    reasoning:
      'مشخصات عرصه ثبتی و ارزش‌گذاری اولیه کارشناسی بدون تغییر عینا در الحاقیه بازتأیید شده است.',
    targetDocA: 'clauseA2',
    targetDocB: 'clauseB1',
  },
  art10: {
    id: 'rel_4',
    key: 'art10',
    title: 'ماده ۱۰ و بند الحاقی ۳',
    category: 'similarity',
    relation: 'مشابه',
    type: 'تکمیل و بقای شرایط عمومی',
    summary: 'تداوم شروط حوادث قهریه و فورس ماژور',
    reasoning:
      'در بند الحاقی ۳ صراحتاً قید شده است که مفاد ماده ۱۰ قرارداد پایه در خصوص شرایط اضطراری و فورس ماژور به همان قوت قانونی باقی است.',
    targetDocA: 'clauseA10',
    targetDocB: 'clauseB3',
  },
};

export const ANALYSIS_STEPS: AnalysisStep[] = [
  {
    id: 1,
    key: 'load_context',
    title: '۱. بارگذاری بافت اسناد و استخراج متن',
    status: 'completed',
    detail: 'تکمیل شده',
  },
  {
    id: 2,
    key: 'load_vector_stores',
    title: '۲. آماده‌سازی پایگاه برداری و بازیابی ترکیبی',
    status: 'completed',
    detail: 'تکمیل شده',
  },
  {
    id: 3,
    key: 'retrieve_candidates',
    title: '۳. بازیابی و تطبیق مواد متناظر (Semantic + BM25)',
    status: 'in_progress',
    detail: 'در حال پردازش...',
  },
  {
    id: 4,
    key: 'analyze_with_llm',
    title: '۴. تحلیل روابط حقوقی و تضادیابی با LLM',
    status: 'queued',
    detail: 'در نوبت اجرا',
  },
  {
    id: 5,
    key: 'completed',
    title: '۵. نهایی‌سازی گزارش تحلیلی',
    status: 'queued',
    detail: 'در نوبت اجرا',
  },
];

// Unified Service Layer Object
export const LegalApiService = {
  getApiBaseUrl,
  setApiBaseUrl,
  getAuthToken,
  setAuthToken,
  removeAuthToken,
  registerUnauthorizedHandler,

  // System
  checkHealth: SystemApi.getHealth,

  // Auth
  authenticate: async (username: string, password: string): Promise<User> => {
    try {
      await AuthApi.login(username, password);
      const user: User = {
        ...CURRENT_USER,
        name: username,
      };
      if (typeof window !== 'undefined') {
        localStorage.setItem(STORAGE_KEY_USER, JSON.stringify(user));
      }
      return user;
    } catch (err) {
      throw err;
    }
  },

  register: async (data: {
    username: string;
    phone?: string;
    password?: string;
  }): Promise<User> => {
    try {
      await AuthApi.register(
        data.username,
        data.phone || '09123456789',
        data.password || 'password123',
        1
      );
      const user: User = {
        ...CURRENT_USER,
        name: data.username,
      };
      if (typeof window !== 'undefined') {
        localStorage.setItem(STORAGE_KEY_USER, JSON.stringify(user));
      }
      return user;
    } catch (err) {
      throw err;
    }
  },

  getCurrentStoredUser: (): User | null => {
    if (typeof window === 'undefined') return null;
    const str = localStorage.getItem(STORAGE_KEY_USER);
    if (!str) return null;
    try {
      return JSON.parse(str);
    } catch {
      return null;
    }
  },

  // Documents
  uploadDocument: DocumentApi.uploadDocument,
  getDocuments: DocumentApi.getDocuments,
  getDocumentStructure: DocumentApi.getDocumentStructure,
  pollStructureStatus: DocumentApi.pollStructureStatus,
  deleteDocument: DocumentApi.deleteDocument,

  // Analyze Workflow
  runWorkflow: AnalyzeApi.runWorkflow,
  getWorkflowStatus: AnalyzeApi.getWorkflowStatus,
  resumeWorkflow: AnalyzeApi.resumeWorkflow,

  // History
  // Uses GET /analyze/history to get items with document_a_id and document_b_id,
  // then fetches each document title via GET /api/v1/document/{document_id}
  // and formats the item title as: "عنوان سند اول، عنوان سند دوم، تاریخ"
  fetchHistory: async (): Promise<HistoryItem[]> => {
    try {
      const items = await HistoryApi.getHistory();
      if (!items || items.length === 0) return [];

      // Backend generates 2 analysis_ids per run (e.g. 1 & 2, 3 & 4).
      // Filter out duplicates and only display odd analysis_ids (1, 3, 5, ...)
      // with natural sequential numbers to user: 1 -> 1, 3 -> 2, 5 -> 3, etc.
      let oddItems = items.filter((item) => item.analysis_id % 2 !== 0);

      // Safeguard: if for any unexpected reason no odd items exist, deduplicate by Math.ceil(analysis_id / 2)
      if (oddItems.length === 0 && items.length > 0) {
        const seen = new Set<number>();
        oddItems = items.filter((item) => {
          const num = Math.ceil(item.analysis_id / 2);
          if (seen.has(num)) return false;
          seen.add(num);
          return true;
        });
      }

      // Collect unique document IDs to fetch titles efficiently with cache
      const docTitlesCache = new Map<number, string>();

      const docIdsToFetch = new Set<number>();
      oddItems.forEach((item) => {
        const idA = item.document_a_id ?? item.doc_a?.doc_id;
        const idB = item.document_b_id ?? item.doc_b?.doc_id;
        if (idA && !item.doc_a?.title) docIdsToFetch.add(idA);
        if (idB && !item.doc_b?.title) docIdsToFetch.add(idB);
      });

      // Pre-fill cache if title was already provided by backend
      oddItems.forEach((item) => {
        if (item.doc_a?.doc_id && item.doc_a.title) {
          docTitlesCache.set(item.doc_a.doc_id, item.doc_a.title);
        }
        if (item.doc_b?.doc_id && item.doc_b.title) {
          docTitlesCache.set(item.doc_b.doc_id, item.doc_b.title);
        }
      });

      // Fetch titles in parallel for all required document IDs
      if (docIdsToFetch.size > 0) {
        await Promise.allSettled(
          Array.from(docIdsToFetch).map(async (docId) => {
            try {
              const doc = await DocumentApi.getDocument(docId);
              if (doc && doc.title) {
                docTitlesCache.set(docId, doc.title);
              }
            } catch (e) {
              console.warn(`Could not fetch document title for doc_id=${docId}:`, e);
              docTitlesCache.set(docId, `سند ${docId}`);
            }
          })
        );
      }

      // Map history items into format:
      // "عنوان سند اول، عنوان سند دوم، تاریخ"
      // Natural user-facing numbering: analysis_id = 1 -> 1, 3 -> 2, 5 -> 3, etc.
      return oddItems.map((item) => {
        const docAId = item.document_a_id ?? item.doc_a?.doc_id;
        const docBId = item.document_b_id ?? item.doc_b?.doc_id;

        const titleA =
          (docAId ? docTitlesCache.get(docAId) : null) ||
          item.doc_a?.title ||
          (docAId ? `سند ${docAId}` : 'سند اول');

        const titleB =
          (docBId ? docTitlesCache.get(docBId) : null) ||
          item.doc_b?.title ||
          (docBId ? `سند ${docBId}` : 'سند دوم');

        const formattedDate = formatPersianDate(item.created_at) || formatPersianTimeAgo(item.created_at);

        // Required prompt format: "عنوان سند اول، عنوان سند دوم، تاریخ"
        const fullDisplayTitle = `${titleA}، ${titleB}، ${formattedDate}`;

        // Natural user-facing display number: (analysis_id + 1) / 2
        const displayNumber = Math.ceil(item.analysis_id / 2);

        return {
          id: `hist_${item.analysis_id}`,
          analysisId: item.analysis_id, // Keeps real backend odd id for API calls
          displayNumber, // Natural sequential number shown to user (1, 2, 3...)
          docAId,
          docBId,
          title: fullDisplayTitle,
          timeAgo: formatPersianTimeAgo(item.created_at),
          formattedDate,
          doc1Name: titleA,
          doc2Name: titleB,
          relationsCount: 0,
        };
      });
    } catch (err) {
      console.warn('Backend history unreachable:', err);
      return [];
    }
  },

  // Compilation & Results Mapping
  compileClausesWithRelations,
  compileDocumentsWithAnalysis,

  fetchHistoryDetail: HistoryApi.getHistoryDetail,
};

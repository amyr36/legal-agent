import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { DocumentInfo } from '../types';
import { DocumentApi, AnalyzeApi } from '../services/api';

const PENDING_DOC1_KEY = 'legal_agent_pending_doc_1';
const PENDING_DOC2_KEY = 'legal_agent_pending_doc_2';

interface UploadScreenProps {
  userName: string;
  doc1?: DocumentInfo | null;
  doc2?: DocumentInfo | null;
  onStartAnalysis: (doc1: DocumentInfo, doc2: DocumentInfo, runId: string) => void;
  onOpenSidebar?: () => void;
}

export const UploadScreen: React.FC<UploadScreenProps> = ({
  userName,
  doc1: initialDoc1 = null,
  doc2: initialDoc2 = null,
  onStartAnalysis,
}) => {
  // Helper to read cached pending document across page refreshes
  const getInitialDoc = (
    propDoc: DocumentInfo | null | undefined,
    storageKey: string
  ): DocumentInfo | null => {
    if (propDoc) return propDoc;
    if (typeof window !== 'undefined') {
      try {
        const saved = sessionStorage.getItem(storageKey);
        if (saved) return JSON.parse(saved);
      } catch (e) {
        console.warn('Error reading stored doc:', e);
      }
    }
    return null;
  };

  // Helper to determine status based on document structureStatus
  const getInitialStatus = (
    doc: DocumentInfo | null
  ): 'idle' | 'uploading' | 'processing' | 'done' | 'failed' => {
    if (!doc) return 'idle';
    if (doc.structureStatus === 'done' || doc.status === 'ready') return 'done';
    if (doc.structureStatus === 'failed') return 'failed';
    if (doc.docId) return 'processing';
    return 'idle';
  };

  const [doc1, setDoc1] = useState<DocumentInfo | null>(() =>
    getInitialDoc(initialDoc1, PENDING_DOC1_KEY)
  );
  const [doc2, setDoc2] = useState<DocumentInfo | null>(() =>
    getInitialDoc(initialDoc2, PENDING_DOC2_KEY)
  );

  const [statusDoc1, setStatusDoc1] = useState<'idle' | 'uploading' | 'processing' | 'done' | 'failed'>(
    () => getInitialStatus(doc1)
  );
  const [statusDoc2, setStatusDoc2] = useState<'idle' | 'uploading' | 'processing' | 'done' | 'failed'>(
    () => getInitialStatus(doc2)
  );

  const [isStartingAnalysis, setIsStartingAnalysis] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const fileInputRef1 = useRef<HTMLInputElement>(null);
  const fileInputRef2 = useRef<HTMLInputElement>(null);

  const isCancelledRef = useRef<boolean>(false);

  useEffect(() => {
    isCancelledRef.current = false;
    return () => {
      isCancelledRef.current = true;
    };
  }, []);

  // Update doc1 / doc2 if props change from outside
  useEffect(() => {
    if (initialDoc1) {
      setDoc1(initialDoc1);
      setStatusDoc1(getInitialStatus(initialDoc1));
    }
  }, [initialDoc1]);

  useEffect(() => {
    if (initialDoc2) {
      setDoc2(initialDoc2);
      setStatusDoc2(getInitialStatus(initialDoc2));
    }
  }, [initialDoc2]);

  // Independent timeout tracking state for doc 1 & doc 2
  const [isTimeoutDoc1, setIsTimeoutDoc1] = useState(false);
  const [isTimeoutDoc2, setIsTimeoutDoc2] = useState(false);

  // Retry trigger counters to restart polling when user clicks "بررسی مجدد"
  const [retryTrigger1, setRetryTrigger1] = useState(0);
  const [retryTrigger2, setRetryTrigger2] = useState(0);

  // Seconds elapsed during processing for user awareness
  const [elapsedSecondsDoc1, setElapsedSecondsDoc1] = useState(0);
  const [elapsedSecondsDoc2, setElapsedSecondsDoc2] = useState(0);

  // Seconds elapsed ticker for Doc 1
  useEffect(() => {
    if (statusDoc1 !== 'processing' || isTimeoutDoc1) return;
    const interval = setInterval(() => {
      setElapsedSecondsDoc1((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [statusDoc1, isTimeoutDoc1]);

  // Seconds elapsed ticker for Doc 2
  useEffect(() => {
    if (statusDoc2 !== 'processing' || isTimeoutDoc2) return;
    const interval = setInterval(() => {
      setElapsedSecondsDoc2((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [statusDoc2, isTimeoutDoc2]);

  // =========================================================================
  // Independent Polling for Document 1
  // - No short 60-attempt limit
  // - Stops ONLY on 'done' or explicit backend failure ('failed' / 'error')
  // - 10-minute safety timeout with "بررسی مجدد" retry button
  // - Progressive backoff (1.5s -> 5s) to reduce backend pressure
  // - Automatic restart if user refreshed or navigated back while processing
  // - Proper interval cleanup on unmount or doc removal
  // =========================================================================
  useEffect(() => {
    if (!doc1?.docId || statusDoc1 !== 'processing') {
      return;
    }

    let isSubscribed = true;
    let timerId: ReturnType<typeof setTimeout> | null = null;
    const startTime = Date.now();
    const MAX_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes safety cap
    let currentInterval = 1500; // Start at 1.5s and backoff to 5s

    setIsTimeoutDoc1(false);
    setUploadError(null);

    const poll = async () => {
      if (!isSubscribed || isCancelledRef.current) return;

      const elapsed = Date.now() - startTime;

      // Check safety cap (10 minutes)
      if (elapsed >= MAX_TIMEOUT_MS) {
        if (isSubscribed) {
          setIsTimeoutDoc1(true);
        }
        return;
      }

      try {
        const check = await DocumentApi.getDocument(doc1.docId!);
        if (!isSubscribed || isCancelledRef.current) return;

        // Terminal status 1: done
        if (check.structure_status === 'done') {
          setStatusDoc1('done');
          setIsTimeoutDoc1(false);
          const updated: DocumentInfo = {
            ...doc1,
            title: check.title || doc1.title,
            structureStatus: 'done',
            status: 'ready',
          };
          setDoc1(updated);
          try {
            sessionStorage.setItem(PENDING_DOC1_KEY, JSON.stringify(updated));
          } catch (_) {}
          return;
        }

        // Terminal status 2: explicit backend failure
        if (
          check.structure_status === 'failed' ||
          (check as any).structure_status === 'error'
        ) {
          setStatusDoc1('failed');
          setIsTimeoutDoc1(false);
          setUploadError('پردازش و ساختاردهی سند اول با خطای سرور مواجه شد.');
          return;
        }

        // Non-terminal: 'pending' or 'processing' or 'partial'
        // Progressive backoff: 1.5s -> 2.2s -> 2.9s -> 3.6s -> 4.3s -> max 5.0s
        currentInterval = Math.min(5000, currentInterval + 700);
      } catch (err: any) {
        // Network blip / transient error: do NOT fail permanently, keep retrying
        console.warn('Doc 1 polling transient check error:', err);
      }

      if (isSubscribed && !isCancelledRef.current) {
        timerId = setTimeout(poll, currentInterval);
      }
    };

    // Kick off initial poll
    poll();

    return () => {
      isSubscribed = false;
      if (timerId) {
        clearTimeout(timerId);
        timerId = null;
      }
    };
  }, [doc1?.docId, statusDoc1, retryTrigger1]);

  // =========================================================================
  // Independent Polling for Document 2
  // =========================================================================
  useEffect(() => {
    if (!doc2?.docId || statusDoc2 !== 'processing') {
      return;
    }

    let isSubscribed = true;
    let timerId: ReturnType<typeof setTimeout> | null = null;
    const startTime = Date.now();
    const MAX_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes safety cap
    let currentInterval = 1500; // Start at 1.5s and backoff to 5s

    setIsTimeoutDoc2(false);
    setUploadError(null);

    const poll = async () => {
      if (!isSubscribed || isCancelledRef.current) return;

      const elapsed = Date.now() - startTime;

      // Check safety cap (10 minutes)
      if (elapsed >= MAX_TIMEOUT_MS) {
        if (isSubscribed) {
          setIsTimeoutDoc2(true);
        }
        return;
      }

      try {
        const check = await DocumentApi.getDocument(doc2.docId!);
        if (!isSubscribed || isCancelledRef.current) return;

        // Terminal status 1: done
        if (check.structure_status === 'done') {
          setStatusDoc2('done');
          setIsTimeoutDoc2(false);
          const updated: DocumentInfo = {
            ...doc2,
            title: check.title || doc2.title,
            structureStatus: 'done',
            status: 'ready',
          };
          setDoc2(updated);
          try {
            sessionStorage.setItem(PENDING_DOC2_KEY, JSON.stringify(updated));
          } catch (_) {}
          return;
        }

        // Terminal status 2: explicit backend failure
        if (
          check.structure_status === 'failed' ||
          (check as any).structure_status === 'error'
        ) {
          setStatusDoc2('failed');
          setIsTimeoutDoc2(false);
          setUploadError('پردازش و ساختاردهی سند دوم با خطای سرور مواجه شد.');
          return;
        }

        // Non-terminal: 'pending' or 'processing' or 'partial'
        // Progressive backoff: 1.5s -> 2.2s -> 2.9s -> 3.6s -> 4.3s -> max 5.0s
        currentInterval = Math.min(5000, currentInterval + 700);
      } catch (err: any) {
        // Network blip / transient error: do NOT fail permanently, keep retrying
        console.warn('Doc 2 polling transient check error:', err);
      }

      if (isSubscribed && !isCancelledRef.current) {
        timerId = setTimeout(poll, currentInterval);
      }
    };

    // Kick off initial poll
    poll();

    return () => {
      isSubscribed = false;
      if (timerId) {
        clearTimeout(timerId);
        timerId = null;
      }
    };
  }, [doc2?.docId, statusDoc2, retryTrigger2]);

  // Upload and track Document 1
  const handleUploadFile1 = async (file: File) => {
    if (file.size > 300 * 1024) {
      setUploadError('حجم فایل انتخابی بیش از ۳۰۰ کیلوبایت است (محدودیت سیستم: حداکثر ۳۰۰ کیلوبایت).');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      setUploadError('تنها فایل‌های با فرمت PDF مجاز هستند.');
      return;
    }

    const kbSize = Math.max(1, Math.round(file.size / 1024));
    const newDoc: DocumentInfo = {
      id: 'doc_1',
      title: file.name.replace(/\.pdf$/i, ''),
      fileName: file.name,
      tag: 'سند اول',
      date: new Date().toLocaleDateString('fa-IR'),
      pageCount: 1,
      fileSize: `${kbSize} کیلوبایت`,
      status: 'pending',
      rawFile: file,
    };

    setDoc1(newDoc);
    setStatusDoc1('uploading');
    setIsTimeoutDoc1(false);
    setElapsedSecondsDoc1(0);
    setUploadError(null);

    try {
      const uploaded = await DocumentApi.uploadDocument(file, newDoc.title);
      if (isCancelledRef.current) return;

      newDoc.docId = uploaded.doc_id;
      newDoc.structureStatus = uploaded.structure_status;
      setDoc1({ ...newDoc });

      try {
        sessionStorage.setItem(PENDING_DOC1_KEY, JSON.stringify(newDoc));
      } catch (_) {}

      if (uploaded.structure_status === 'done') {
        setStatusDoc1('done');
      } else {
        setStatusDoc1('processing');
      }
    } catch (err: any) {
      if (isCancelledRef.current) return;
      console.error('Doc 1 upload error:', err);
      setStatusDoc1('failed');
      setUploadError(err.message || 'خطا در بارگذاری سند اول در سرور');
    }
  };

  // Upload and track Document 2
  const handleUploadFile2 = async (file: File) => {
    if (file.size > 300 * 1024) {
      setUploadError('حجم فایل انتخابی بیش از ۳۰۰ کیلوبایت است (محدودیت سیستم: حداکثر ۳۰۰ کیلوبایت).');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      setUploadError('تنها فایل‌های با فرمت PDF مجاز هستند.');
      return;
    }

    const kbSize = Math.max(1, Math.round(file.size / 1024));
    const newDoc: DocumentInfo = {
      id: 'doc_2',
      title: file.name.replace(/\.pdf$/i, ''),
      fileName: file.name,
      tag: 'سند دوم',
      date: new Date().toLocaleDateString('fa-IR'),
      pageCount: 1,
      fileSize: `${kbSize} کیلوبایت`,
      status: 'pending',
      rawFile: file,
    };

    setDoc2(newDoc);
    setStatusDoc2('uploading');
    setIsTimeoutDoc2(false);
    setElapsedSecondsDoc2(0);
    setUploadError(null);

    try {
      const uploaded = await DocumentApi.uploadDocument(file, newDoc.title);
      if (isCancelledRef.current) return;

      newDoc.docId = uploaded.doc_id;
      newDoc.structureStatus = uploaded.structure_status;
      setDoc2({ ...newDoc });

      try {
        sessionStorage.setItem(PENDING_DOC2_KEY, JSON.stringify(newDoc));
      } catch (_) {}

      if (uploaded.structure_status === 'done') {
        setStatusDoc2('done');
      } else {
        setStatusDoc2('processing');
      }
    } catch (err: any) {
      if (isCancelledRef.current) return;
      console.error('Doc 2 upload error:', err);
      setStatusDoc2('failed');
      setUploadError(err.message || 'خطا در بارگذاری سند دوم در سرور');
    }
  };

  const handleRetryDoc1 = () => {
    setIsTimeoutDoc1(false);
    setElapsedSecondsDoc1(0);
    setStatusDoc1('processing');
    setRetryTrigger1((prev) => prev + 1);
  };

  const handleRetryDoc2 = () => {
    setIsTimeoutDoc2(false);
    setElapsedSecondsDoc2(0);
    setStatusDoc2('processing');
    setRetryTrigger2((prev) => prev + 1);
  };

  const handleRemoveDoc1 = () => {
    setDoc1(null);
    setStatusDoc1('idle');
    setIsTimeoutDoc1(false);
    setElapsedSecondsDoc1(0);
    try {
      sessionStorage.removeItem(PENDING_DOC1_KEY);
    } catch (_) {}
  };

  const handleRemoveDoc2 = () => {
    setDoc2(null);
    setStatusDoc2('idle');
    setIsTimeoutDoc2(false);
    setElapsedSecondsDoc2(0);
    try {
      sessionStorage.removeItem(PENDING_DOC2_KEY);
    } catch (_) {}
  };

  const handleFileChange1 = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleUploadFile1(e.target.files[0]);
    }
  };

  const handleFileChange2 = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleUploadFile2(e.target.files[0]);
    }
  };

  // Dropzone handlers
  const handleDrop1 = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUploadFile1(e.dataTransfer.files[0]);
    }
  };

  const handleDrop2 = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUploadFile2(e.dataTransfer.files[0]);
    }
  };

  // Both documents must have done structure before analysis is unlocked
  const isBothDone = Boolean(
    doc1?.docId &&
    doc2?.docId &&
    statusDoc1 === 'done' &&
    statusDoc2 === 'done'
  );

  const isBuildingDatabase =
    statusDoc1 === 'uploading' ||
    statusDoc1 === 'processing' ||
    statusDoc2 === 'uploading' ||
    statusDoc2 === 'processing';

  // Trigger analysis workflow when both are done
  const handleStartAnalysis = async () => {
    if (!doc1?.docId || !doc2?.docId || !isBothDone) {
      return;
    }

    setIsStartingAnalysis(true);
    setUploadError(null);

    try {
      // Send both doc_ids via /analyze/workflow/run
      const runRes = await AnalyzeApi.runWorkflow(doc1.docId, doc2.docId);
      // Navigate to ProcessingScreen with the run_id
      onStartAnalysis(doc1, doc2, runRes.run_id);
    } catch (err: any) {
      console.error('Failed to run workflow:', err);
      setIsStartingAnalysis(false);
      setUploadError(err.message || 'خطا در شروع تحلیل در سرور');
    }
  };

  return (
    <div className="relative min-h-screen w-full flex flex-col justify-between overflow-x-hidden bg-[#f7f3ec] text-[#1c1c18]">
      {/* Main Container */}
      <main className="flex-1 w-full max-w-5xl mx-auto px-6 py-8 md:py-10 flex flex-col justify-center">
        <div className="w-full flex-1 flex flex-col justify-center my-auto">
          {/* Welcome & Instruction Hero */}
          <section className="text-center mb-8">
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/90 border border-[#E8E4DB] shadow-sm text-xs font-semibold text-[#1F2721] mb-4 backdrop-blur-sm"
            >
              <span className="w-2 h-2 rounded-full bg-[#5C7A60] animate-pulse"></span>
              <span>سامانه هوشمند تشخیص تشابه و تناقض در اسناد قوانین تخصصی</span>
            </motion.div>

            <motion.h1
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="text-2xl sm:text-3xl lg:text-4xl font-extrabold text-[#141A15] tracking-tight"
            >
              {userName} عزیز، خوش آمدید
            </motion.h1>

            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.2 }}
              className="mt-3 text-sm sm:text-base text-[#71756E] max-w-2xl mx-auto font-normal leading-relaxed"
            >
              جهت تحلیل هوشمند و تشخیص تناقضات و تشابهات موجود، اسناد خود را بارگذاری کنید
            </motion.p>
          </section>

          {/* Validation Alert */}
          <AnimatePresence>
            {uploadError && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="mb-5 p-3.5 rounded-2xl bg-red-50 border border-red-200 text-red-700 text-xs font-medium flex items-center justify-between shadow-sm"
              >
                <div className="flex items-center gap-2.5">
                  <span className="material-symbols-outlined text-[20px] text-red-600">error</span>
                  <span>{uploadError}</span>
                </div>
                <button
                  onClick={() => setUploadError(null)}
                  className="text-red-500 hover:text-red-700 p-1 rounded-lg cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[16px]">close</span>
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Upload Cards Grid */}
          <section className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-7">
            {/* Document 1: سند اول */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.25 }}
              className={`rounded-3xl p-6 glass-surface shadow-md border flex flex-col justify-between transition-all ${
                !doc1 && uploadError
                  ? 'border-red-400 ring-2 ring-red-200 bg-red-50/20'
                  : 'border-white/90'
              }`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop1}
            >
              <div>
                {/* Header */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2.5">
                    <span className="w-7 h-7 rounded-xl bg-[#E8EFE9] text-[#3D5241] font-bold text-xs flex items-center justify-center border border-[#D2DFD4]">
                      ۱
                    </span>
                    <div>
                      <h3 className="font-bold text-[#141A15] text-sm">سند اول</h3>
                    </div>
                  </div>

                  {/* Status Badge */}
                  {statusDoc1 === 'done' ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-[#E8EFE9] text-[#3D5241] border border-[#D2DFD4]/80">
                      <span className="material-symbols-outlined text-[14px] text-[#4A634E]">check_circle</span>
                      <span>پایگاه داده ساخته شد</span>
                    </span>
                  ) : isTimeoutDoc1 ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-900 border border-amber-300">
                      <span className="material-symbols-outlined text-[14px] text-amber-700">timer</span>
                      <span>پایان مهلت انتظار</span>
                    </span>
                  ) : statusDoc1 === 'processing' ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-200/80">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-600 animate-ping"></span>
                      <span>درحال ساخت پایگاه داده...</span>
                      {elapsedSecondsDoc1 > 0 && (
                        <span className="text-[10px] text-amber-700 font-mono">
                          ({Math.floor(elapsedSecondsDoc1 / 60)}:{String(elapsedSecondsDoc1 % 60).padStart(2, '0')})
                        </span>
                      )}
                    </span>
                  ) : statusDoc1 === 'uploading' ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200/80">
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse"></span>
                      <span>در حال ارسال سند...</span>
                    </span>
                  ) : statusDoc1 === 'failed' ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-red-50 text-red-700 border border-red-200">
                      <span className="material-symbols-outlined text-[14px]">error</span>
                      <span>خطا در پردازش</span>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-[#FAF8F4] text-[#71756E] border border-[#E8E4DB]/70">
                      <span>منتظر انتخاب فایل</span>
                    </span>
                  )}
                </div>

                {/* File Upload Box */}
                {doc1 ? (
                  <div className="p-4 rounded-2xl bg-white border border-[#E8E4DB]/80 shadow-inner flex flex-col justify-center min-h-[118px]">
                    <div className="flex items-center justify-between gap-3 w-full">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-10 h-10 rounded-xl bg-[#E8EFE9] text-[#3D5241] flex items-center justify-center shrink-0 border border-[#D2DFD4]/60">
                          <span className="material-symbols-outlined text-[22px]">description</span>
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-bold text-[#141A15] truncate" title={doc1.fileName}>
                            {doc1.fileName}
                          </p>
                          <p className="text-[10px] text-[#71756E] mt-0.5">
                            {doc1.fileSize || 'سند PDF'} •{' '}
                            {statusDoc1 === 'done'
                              ? 'آماده تحلیل'
                              : isTimeoutDoc1
                              ? 'نیاز به بررسی وضعیت'
                              : statusDoc1 === 'processing'
                              ? 'درحال ساخت پایگاه داده'
                              : statusDoc1 === 'uploading'
                              ? 'در حال بارگذاری'
                              : 'نیاز به بررسی'}
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={handleRemoveDoc1}
                        className="text-[#71756E] hover:text-rose-600 p-1.5 rounded-lg hover:bg-rose-50 transition-colors shrink-0 cursor-pointer"
                        title="حذف فایل"
                      >
                        <span className="material-symbols-outlined text-[18px]">close</span>
                      </button>
                    </div>

                    {/* Timeout Alert with Retry Button */}
                    {isTimeoutDoc1 && (
                      <div className="mt-3 p-3 rounded-xl bg-amber-50 border border-amber-300 text-amber-950 text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5">
                        <div className="flex items-start gap-2">
                          <span className="material-symbols-outlined text-[18px] text-amber-700 shrink-0 mt-0.5">
                            schedule
                          </span>
                          <span className="leading-relaxed">
                            زمان بررسی بیش از حد انتظار به طول انجامید، اما پردازش ممکن است در سرور کامل شده باشد.
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={handleRetryDoc1}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-700 hover:bg-amber-800 text-white font-semibold text-xs shadow-xs transition cursor-pointer shrink-0"
                        >
                          <span className="material-symbols-outlined text-[15px]">sync</span>
                          <span>بررسی مجدد</span>
                        </button>
                      </div>
                    )}

                    {/* Informative Long Processing Notice (Not Red Error) */}
                    {statusDoc1 === 'processing' && !isTimeoutDoc1 && elapsedSecondsDoc1 >= 15 && (
                      <div className="mt-3 p-2.5 rounded-xl bg-amber-50/60 border border-amber-200/60 text-amber-900 text-[11px] flex items-center gap-2">
                        <span className="material-symbols-outlined text-[16px] text-amber-700 animate-spin shrink-0">
                          progress_activity
                        </span>
                        <span className="leading-relaxed">
                          استخراج متن و ساخت بردارها ممکن است تا چند دقیقه طول بکشد، لطفاً شکیبا باشید...
                        </span>
                      </div>
                    )}

                    {/* Success indicator */}
                    {statusDoc1 === 'done' && (
                      <div className="mt-3 p-2 rounded-xl bg-[#E8EFE9]/70 border border-[#D2DFD4]/70 text-[#2B3B2E] text-[11px] flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[15px] text-[#4A634E]">check_circle</span>
                        <span>ساختار سند استخراج شد و آماده مقایسه است.</span>
                      </div>
                    )}
                  </div>
                ) : (
                  <div
                    onClick={() => fileInputRef1.current?.click()}
                    className="cursor-pointer p-4 rounded-2xl bg-[#FAF8F4]/80 border-2 border-dashed border-[#D2DFD4]/90 hover:border-[#5C7A60] hover:bg-white transition-all flex flex-col items-center justify-center text-center group min-h-[118px]"
                  >
                    <div className="w-10 h-10 rounded-xl bg-white shadow-sm border border-[#E8E4DB] group-hover:bg-[#E8EFE9] group-hover:text-[#3D5241] text-[#71756E] flex items-center justify-center transition-colors mb-2">
                      <span className="material-symbols-outlined text-[22px]">upload_file</span>
                    </div>
                    <p className="text-xs font-bold text-[#1F2721] group-hover:text-[#141A15]">
                      کلیک برای انتخاب سند یا کشیدن فایل به اینجا
                    </p>
                    <p className="text-[10px] text-[#71756E] mt-1">فرمت مجاز: فایل PDF (حداکثر ۳۰۰ کیلوبایت)</p>
                  </div>
                )}
              </div>

              {/* Card Footer */}
              <div className="mt-4 pt-3 border-t border-[#E8E4DB]/60 flex items-center justify-between text-xs text-[#71756E]">
                <button
                  type="button"
                  onClick={() => fileInputRef1.current?.click()}
                  className="inline-flex items-center gap-1 text-[#3D5241] hover:text-[#1F2721] font-semibold transition cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[16px]">swap_horiz</span>
                  <span>تغییر فایل</span>
                </button>
                <span className="text-[11px] text-[#71756E]">
                  {doc1?.docId ? `شناسه سند در سیستم: ${doc1.docId}` : 'حداکثر سقف مجاز: ۳۰۰ کیلوبایت'}
                </span>
                <input
                  ref={fileInputRef1}
                  type="file"
                  accept=".pdf,application/pdf"
                  className="hidden"
                  onChange={handleFileChange1}
                />
              </div>
            </motion.div>

            {/* Document 2: سند دوم */}
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 }}
              className={`rounded-3xl p-6 glass-surface shadow-md border flex flex-col justify-between transition-all ${
                !doc2 && uploadError
                  ? 'border-red-400 ring-2 ring-red-200 bg-red-50/20'
                  : 'border-white/90'
              }`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop2}
            >
              <div>
                {/* Header */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2.5">
                    <span className="w-7 h-7 rounded-xl bg-[#F4F7F4] text-[#3D5241] font-bold text-xs flex items-center justify-center border border-[#D2DFD4]">
                      ۲
                    </span>
                    <div>
                      <h3 className="font-bold text-[#141A15] text-sm">سند دوم</h3>
                    </div>
                  </div>

                  {/* Status Badge */}
                  {statusDoc2 === 'done' ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-[#E8EFE9] text-[#3D5241] border border-[#D2DFD4]/80">
                      <span className="material-symbols-outlined text-[14px] text-[#4A634E]">check_circle</span>
                      <span>پایگاه داده ساخته شد</span>
                    </span>
                  ) : isTimeoutDoc2 ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-900 border border-amber-300">
                      <span className="material-symbols-outlined text-[14px] text-amber-700">timer</span>
                      <span>پایان مهلت انتظار</span>
                    </span>
                  ) : statusDoc2 === 'processing' ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-200/80">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-600 animate-ping"></span>
                      <span>درحال ساخت پایگاه داده...</span>
                      {elapsedSecondsDoc2 > 0 && (
                        <span className="text-[10px] text-amber-700 font-mono">
                          ({Math.floor(elapsedSecondsDoc2 / 60)}:{String(elapsedSecondsDoc2 % 60).padStart(2, '0')})
                        </span>
                      )}
                    </span>
                  ) : statusDoc2 === 'uploading' ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200/80">
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse"></span>
                      <span>در حال ارسال سند...</span>
                    </span>
                  ) : statusDoc2 === 'failed' ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-red-50 text-red-700 border border-red-200">
                      <span className="material-symbols-outlined text-[14px]">error</span>
                      <span>خطا در پردازش</span>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-[#FAF8F4] text-[#71756E] border border-[#E8E4DB]/70">
                      <span>منتظر انتخاب فایل</span>
                    </span>
                  )}
                </div>

                {/* Dropzone Box */}
                {doc2 ? (
                  <div className="p-4 rounded-2xl bg-white border border-[#E8E4DB]/80 shadow-inner flex flex-col justify-center min-h-[118px]">
                    <div className="flex items-center justify-between gap-3 w-full">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-10 h-10 rounded-xl bg-[#E8EFE9] text-[#3D5241] flex items-center justify-center shrink-0 border border-[#D2DFD4]/60">
                          <span className="material-symbols-outlined text-[22px]">description</span>
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-bold text-[#141A15] truncate" title={doc2.fileName}>
                            {doc2.fileName}
                          </p>
                          <p className="text-[10px] text-[#71756E] mt-0.5">
                            {doc2.fileSize || 'سند PDF'} •{' '}
                            {statusDoc2 === 'done'
                              ? 'آماده تحلیل'
                              : isTimeoutDoc2
                              ? 'نیاز به بررسی وضعیت'
                              : statusDoc2 === 'processing'
                              ? 'درحال ساخت پایگاه داده'
                              : statusDoc2 === 'uploading'
                              ? 'در حال بارگذاری'
                              : 'نیاز به بررسی'}
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={handleRemoveDoc2}
                        className="text-[#71756E] hover:text-rose-600 p-1.5 rounded-lg hover:bg-rose-50 transition-colors shrink-0 cursor-pointer"
                        title="حذف فایل"
                      >
                        <span className="material-symbols-outlined text-[18px]">close</span>
                      </button>
                    </div>

                    {/* Timeout Alert with Retry Button */}
                    {isTimeoutDoc2 && (
                      <div className="mt-3 p-3 rounded-xl bg-amber-50 border border-amber-300 text-amber-950 text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5">
                        <div className="flex items-start gap-2">
                          <span className="material-symbols-outlined text-[18px] text-amber-700 shrink-0 mt-0.5">
                            schedule
                          </span>
                          <span className="leading-relaxed">
                            زمان بررسی بیش از حد انتظار به طول انجامید، اما پردازش ممکن است در سرور کامل شده باشد.
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={handleRetryDoc2}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-700 hover:bg-amber-800 text-white font-semibold text-xs shadow-xs transition cursor-pointer shrink-0"
                        >
                          <span className="material-symbols-outlined text-[15px]">sync</span>
                          <span>بررسی مجدد</span>
                        </button>
                      </div>
                    )}

                    {/* Informative Long Processing Notice (Not Red Error) */}
                    {statusDoc2 === 'processing' && !isTimeoutDoc2 && elapsedSecondsDoc2 >= 15 && (
                      <div className="mt-3 p-2.5 rounded-xl bg-amber-50/60 border border-amber-200/60 text-amber-900 text-[11px] flex items-center gap-2">
                        <span className="material-symbols-outlined text-[16px] text-amber-700 animate-spin shrink-0">
                          progress_activity
                        </span>
                        <span className="leading-relaxed">
                          استخراج متن و ساخت بردارها ممکن است تا چند دقیقه طول بکشد، لطفاً شکیبا باشید...
                        </span>
                      </div>
                    )}

                    {/* Success indicator */}
                    {statusDoc2 === 'done' && (
                      <div className="mt-3 p-2 rounded-xl bg-[#E8EFE9]/70 border border-[#D2DFD4]/70 text-[#2B3B2E] text-[11px] flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[15px] text-[#4A634E]">check_circle</span>
                        <span>ساختار سند استخراج شد و آماده مقایسه است.</span>
                      </div>
                    )}
                  </div>
                ) : (
                  <div
                    onClick={() => fileInputRef2.current?.click()}
                    className="cursor-pointer p-4 rounded-2xl bg-[#FAF8F4]/80 border-2 border-dashed border-[#D2DFD4]/90 hover:border-[#5C7A60] hover:bg-white transition-all flex flex-col items-center justify-center text-center group min-h-[118px]"
                  >
                    <div className="w-10 h-10 rounded-xl bg-white shadow-sm border border-[#E8E4DB] group-hover:bg-[#E8EFE9] group-hover:text-[#3D5241] text-[#71756E] flex items-center justify-center transition-colors mb-2">
                      <span className="material-symbols-outlined text-[22px]">upload_file</span>
                    </div>
                    <p className="text-xs font-bold text-[#1F2721] group-hover:text-[#141A15]">
                      کلیک برای انتخاب سند یا کشیدن فایل به اینجا
                    </p>
                    <p className="text-[10px] text-[#71756E] mt-1">فرمت مجاز: فایل PDF (حداکثر ۳۰۰ کیلوبایت)</p>
                  </div>
                )}
              </div>

              {/* Card Footer */}
              <div className="mt-4 pt-3 border-t border-[#E8E4DB]/60 flex items-center justify-between text-xs text-[#71756E]">
                <button
                  type="button"
                  onClick={() => fileInputRef2.current?.click()}
                  className="inline-flex items-center gap-1 text-[#3D5241] hover:text-[#1F2721] font-semibold transition cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[16px]">swap_horiz</span>
                  <span>تغییر فایل</span>
                </button>
                <span className="text-[11px] text-[#71756E]">
                  {doc2?.docId ? `شناسه سند در سیستم: ${doc2.docId}` : 'حداکثر سقف مجاز: ۳۰۰ کیلوبایت'}
                </span>
                <input
                  ref={fileInputRef2}
                  type="file"
                  accept=".pdf,application/pdf"
                  className="hidden"
                  onChange={handleFileChange2}
                />
              </div>
            </motion.div>
          </section>

          {/* Action Area: Start Analysis Button & Status Indicator */}
          <section className="flex flex-col items-center justify-center mt-2">
            <motion.button
              whileHover={isBothDone && !isStartingAnalysis ? { scale: 1.02 } : {}}
              whileTap={isBothDone && !isStartingAnalysis ? { scale: 0.98 } : {}}
              disabled={!isBothDone || isStartingAnalysis}
              onClick={handleStartAnalysis}
              className={`px-10 py-3.5 rounded-2xl font-bold text-sm sm:text-base shadow-xl transition-all duration-300 flex items-center gap-3 border ${
                isBothDone && !isStartingAnalysis
                  ? 'bg-gradient-to-l from-[#141A15] via-[#1F2721] to-[#324235] hover:from-[#1F2721] hover:to-[#4A634E] text-white border-[#3D5241]/60 cursor-pointer shadow-lg hover:shadow-2xl'
                  : 'bg-[#DCD8CF] text-[#8C8880] border-[#CBC6BC] cursor-not-allowed opacity-75 shadow-none'
              }`}
              id="startCompareBtn"
            >
              <div
                className={`w-7 h-7 rounded-xl flex items-center justify-center font-extrabold shadow transition-transform ${
                  isBothDone ? 'bg-[#ADC4B0] text-[#141A15]' : 'bg-[#CCC7BC] text-[#7A766E]'
                }`}
              >
                {isStartingAnalysis ? (
                  <span className="w-4 h-4 border-2 border-[#141A15] border-t-transparent rounded-full animate-spin"></span>
                ) : (
                  <span className="material-symbols-outlined text-[18px]">auto_awesome</span>
                )}
              </div>
              <span>
                {isStartingAnalysis
                  ? 'در حال ارسال درخواست و شروع فرآیند تحلیل...'
                  : 'شروع تحلیل و تطبیق هوشمند اسناد'}
              </span>
              <span
                className={`material-symbols-outlined text-[20px] transition-transform ${
                  isBothDone ? 'text-[#ADC4B0]' : 'text-[#8C8880]'
                }`}
              >
                arrow_left_alt
              </span>
            </motion.button>

            {/* Subtext under button: Required by prompt */}
            <div className="mt-3 flex items-center justify-center min-h-[24px]">
              {isBuildingDatabase ? (
                <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-amber-50/90 border border-amber-200 text-amber-800 text-xs font-semibold shadow-xs">
                  <span className="w-2 h-2 rounded-full bg-amber-600 animate-ping"></span>
                  <span>درحال ساخت پایگاه داده و استخراج هوشمند اسناد</span>
                  <span className="text-[11px] text-amber-700 font-normal">
                    (پردازش ممکن است تا چند دقیقه طول بکشد)
                  </span>
                </div>
              ) : isBothDone ? (
                <div className="inline-flex items-center gap-1.5 px-3.5 py-1 rounded-full bg-[#E8EFE9] border border-[#D2DFD4] text-[#3D5241] text-xs font-semibold shadow-xs">
                  <span className="material-symbols-outlined text-[15px] text-[#4A634E]">verified</span>
                  <span>پایگاه داده هر دو سند ساخته شد • آماده شروع تحلیل</span>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
};

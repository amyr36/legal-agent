import React, { useEffect, useState, useRef } from 'react';
import {
  DocumentInfo,
  Clause,
  Relation,
  WorkflowStep,
} from '../types';
import {
  DocumentApi,
  AnalyzeApi,
  compileDocumentsWithAnalysis,
} from '../services/api';

interface ProcessingScreenProps {
  doc1: DocumentInfo;
  doc2: DocumentInfo;
  isRetry?: boolean;
  runId?: string | null;
  initialStep?: number;
  initialProgress?: number;
  onComplete: (data: {
    runId: string;
    analysisId?: number | null;
    relations: Record<string, Relation>;
    clausesDoc1: Clause[];
    clausesDoc2: Clause[];
  }) => void;
  onError: (
    errorMsg: string,
    runId?: string | null,
    details?: { failedStep?: number; progress?: number; statusMessage?: string }
  ) => void;
  onOpenSidebar?: () => void;
}

export const ProcessingScreen: React.FC<ProcessingScreenProps> = ({
  doc1,
  doc2,
  isRetry = false,
  runId: initialRunId = null,
  initialStep = 1,
  initialProgress = 12,
  onComplete,
  onError,
}) => {
  const [activeStep, setActiveStep] = useState<number>(isRetry ? (initialStep || 3) : 1);
  const [progress, setProgress] = useState<number>(isRetry ? (initialProgress || 68) : 12);
  const [statusMessage, setStatusMessage] = useState<string>(
    isRetry
      ? `ادامه فرآیند تحلیل از مرحله ${initialStep || 3} پس از اتصال مجدد...`
      : 'در حال آماده‌سازی و ارتباط با سرور...'
  );
  const [stepStates, setStepStates] = useState<{
    [key: number]: 'completed' | 'in_progress' | 'queued';
  }>(() => {
    if (isRetry) {
      const startStep = initialStep || 3;
      const states: { [key: number]: 'completed' | 'in_progress' | 'queued' } = {};
      for (let i = 1; i <= 5; i++) {
        if (i < startStep) states[i] = 'completed';
        else if (i === startStep) states[i] = 'in_progress';
        else states[i] = 'queued';
      }
      return states;
    }
    return {
      1: 'in_progress',
      2: 'queued',
      3: 'queued',
      4: 'queued',
      5: 'queued',
    };
  });

  const activeRunIdRef = useRef<string | null>(initialRunId);
  const isCancelledRef = useRef<boolean>(false);
  const activeStepRef = useRef<number>(isRetry ? (initialStep || 3) : 1);
  const progressRef = useRef<number>(isRetry ? (initialProgress || 68) : 12);
  const statusMessageRef = useRef<string>(statusMessage);

  useEffect(() => {
    activeStepRef.current = activeStep;
  }, [activeStep]);

  useEffect(() => {
    progressRef.current = progress;
  }, [progress]);

  useEffect(() => {
    statusMessageRef.current = statusMessage;
  }, [statusMessage]);

  const reportError = (msg: string, customStep?: number) => {
    const step = customStep || activeStepRef.current || 1;
    const defaultPct =
      step === 1 ? 25 : step === 2 ? 50 : step === 3 ? 68 : step === 4 ? 88 : 95;
    const pct = progressRef.current || defaultPct;
    onError(msg, activeRunIdRef.current, {
      failedStep: step,
      progress: pct,
      statusMessage: statusMessageRef.current,
    });
  };

  useEffect(() => {
    isCancelledRef.current = false;

    const executeWorkflow = async () => {
      try {
        // Step 1: Ensure document IDs exist
        let docAId = doc1.docId;
        let docBId = doc2.docId;

        // Upload Doc 1 if rawFile exists and not yet uploaded
        if (doc1.rawFile && !docAId) {
          setStatusMessage('بارگذاری و ساختاردهی سند اول...');
          setActiveStep(1);
          const uploadedA = await DocumentApi.uploadDocument(doc1.rawFile, doc1.title || 'سند اول');
          docAId = uploadedA.doc_id;
          await DocumentApi.pollStructureStatus(docAId);
        }

        if (isCancelledRef.current) return;

        // Upload Doc 2 if rawFile exists and not yet uploaded
        if (doc2.rawFile && !docBId) {
          setStatusMessage('بارگذاری و ساختاردهی سند دوم...');
          setActiveStep(1);
          const uploadedB = await DocumentApi.uploadDocument(doc2.rawFile, doc2.title || 'سند دوم');
          docBId = uploadedB.doc_id;
          await DocumentApi.pollStructureStatus(docBId);
        }

        if (isCancelledRef.current) return;

        if (!docAId || !docBId) {
          throw new Error('شناسه‌های ساختاری اسناد جهت آغاز تحلیل در دسترس نیستند.');
        }

        // Step 2: Trigger / Resume Workflow
        let runId = activeRunIdRef.current;
        if (isRetry && runId) {
          setStatusMessage('تلاش مجدد و ادامه فرآیند تحلیل از آخرین چک‌پوینت...');
          await AnalyzeApi.resumeWorkflow(runId);
        } else if (!runId) {
          setStatusMessage('شروع مقایسه و تحلیل اسناد در پس‌زمینه...');
          const runRes = await AnalyzeApi.runWorkflow(docAId, docBId);
          runId = runRes.run_id;
          activeRunIdRef.current = runId;
        }

        if (!runId) {
          throw new Error('عدم دریافت شناسه اجرای تحلیل از سرور');
        }

        // Initial status message for polling
        setStatusMessage('در حال پیگیری وضعیت تحلیل از سرور...');
        setActiveStep(2);
        setStepStates({
          1: 'completed',
          2: 'in_progress',
          3: 'queued',
          4: 'queued',
          5: 'queued',
        });

        // Step 3 & 4: Run Polling against status endpoint (/analyze/status/{run_id})
        // Increased polling interval as requested to avoid excessive requests to backend
        const RUN_POLLING_INTERVAL_MS = 4000;
        let completed = false;
        while (!completed && !isCancelledRef.current) {
          await new Promise((r) => setTimeout(r, RUN_POLLING_INTERVAL_MS));
          if (isCancelledRef.current) return;

          const statusRes = await AnalyzeApi.getWorkflowStatus(runId);

          if (statusRes.status === 'failed') {
            let failedStepNum = activeStepRef.current;
            if (statusRes.step === 'load_context') failedStepNum = 1;
            else if (statusRes.step === 'load_vector_stores') failedStepNum = 2;
            else if (statusRes.step === 'retrieve_candidates') failedStepNum = 3;
            else if (statusRes.step === 'analyze_with_llm') failedStepNum = 4;
            reportError(statusRes.error || 'خطا در اجرای فرآیند تحلیل در سرور', failedStepNum);
            return;
          }

          if (statusRes.status === 'queued') {
            setActiveStep(1);
            setProgress(20);
            setStatusMessage('در صف پردازش هوش مصنوعی...');
          } else if (statusRes.status === 'running') {
            const step = statusRes.step as WorkflowStep;
            if (step === 'load_context') {
              setActiveStep(1);
              setStepStates({
                1: 'in_progress',
                2: 'queued',
                3: 'queued',
                4: 'queued',
                5: 'queued',
              });
              setProgress(28);
              setStatusMessage('بارگذاری بافت اسناد و استخراج متن...');
            } else if (step === 'load_vector_stores') {
              setActiveStep(2);
              setStepStates({
                1: 'completed',
                2: 'in_progress',
                3: 'queued',
                4: 'queued',
                5: 'queued',
              });
              setProgress(50);
              setStatusMessage('آماده‌سازی پایگاه برداری و بازیابی ترکیبی...');
            } else if (step === 'retrieve_candidates') {
              setActiveStep(3);
              setStepStates({
                1: 'completed',
                2: 'completed',
                3: 'in_progress',
                4: 'queued',
                5: 'queued',
              });
              setProgress(72);
              setStatusMessage('بازیابی و تطبیق مواد متناظر (Semantic + BM25)...');
            } else if (step === 'analyze_with_llm') {
              setActiveStep(4);
              setStepStates({
                1: 'completed',
                2: 'completed',
                3: 'completed',
                4: 'in_progress',
                5: 'queued',
              });
              setProgress(90);
              setStatusMessage('تحلیل روابط حقوقی و تضادیابی با هوش مصنوعی...');
            }
          } else if (statusRes.status === 'completed') {
            completed = true;

            // Step 5: Preparing report & compiling documents in background
            setActiveStep(5);
            setStepStates({
              1: 'completed',
              2: 'completed',
              3: 'completed',
              4: 'completed',
              5: 'in_progress',
            });
            setProgress(92);
            setStatusMessage('آماده‌سازی گزارش • در حال دریافت متن کامل دو سند از سرور...');

            // Compile documents and project relations onto compiled clauses in background
            const compiledResult = await compileDocumentsWithAnalysis({
              docAId,
              docBId,
              analysisId: statusRes.analysis_id,
              relations: statusRes.relations || [],
              onProgress: (msg, pct) => {
                if (pct) setProgress(pct);
                setStatusMessage(`آماده‌سازی گزارش • ${msg}`);
              },
            });

            if (isCancelledRef.current) return;

            // Mark compilation and output preparation complete
            setProgress(100);
            setStepStates({
              1: 'completed',
              2: 'completed',
              3: 'completed',
              4: 'completed',
              5: 'completed',
            });
            setStatusMessage('اسناد کامپایل شدند و نتایج تحلیل آماده نمایش است.');

            // Smooth transition after compilation is done and results are ready to show
            setTimeout(() => {
              if (isCancelledRef.current) return;
              onComplete({
                runId,
                analysisId: statusRes.analysis_id,
                relations: compiledResult.relations,
                clausesDoc1: compiledResult.clausesDoc1,
                clausesDoc2: compiledResult.clausesDoc2,
              });
            }, 700);
            return;
          }
        }
      } catch (err: any) {
        console.error('Workflow error:', err);
        reportError(err.message || 'خطا در اجرای فرآیند تحلیل در سرور', activeStepRef.current);
      }
    };

    executeWorkflow();

    return () => {
      isCancelledRef.current = true;
    };
  }, [isRetry, onError, onComplete, doc1, doc2]);

  // Circumference for r=40 is 2 * PI * 40 ≈ 251.2
  const strokeDashoffset = 251.2 - (251.2 * progress) / 100;

  const stepTitles: { [key: number]: string } = {
    1: 'گام ۱ از ۵: استخراج متن و پردازش متن',
    2: 'گام ۲ از ۵: آماده سازی جستجوی معنایی و متنی',
    3: 'گام ۳ از ۵: جستجوی معنایی و متنی',
    4: 'گام ۴ از ۵: پردازش هوش مصنوعی و مدل زبانی (LLM)',
    5: 'گام ۵ از ۵: آماده سازی گزارش و کامپایل اسناد',
  };

  return (
    <div className="relative min-h-screen w-full flex flex-col justify-between overflow-x-hidden bg-[#f7f3ec] text-[#1c1c18]">
      {/* Main Container */}
      <main className="flex-1 w-full max-w-5xl mx-auto px-6 py-8 md:py-10 flex flex-col justify-center">
        <div className="w-full flex-1 flex flex-col justify-center my-auto">
          {/* Welcome & Instruction Hero */}
          <section className="text-center mb-9">
            <h1 className="text-2xl sm:text-3xl lg:text-4xl font-extrabold text-[#141A15] tracking-tight flex items-center justify-center gap-2.5">
              <span>در حال تحلیل اسناد شما هستیم...</span>
              <span className="material-symbols-outlined text-[#3D5241] animate-spin text-[28px]">
                sync
              </span>
            </h1>
            <p className="mt-3 text-sm text-[#71756E] max-w-2xl mx-auto font-normal leading-relaxed">
              سیستم در حال پردازش واژگانی، انطباق مواد قانونی و سنجش تعارضات میان دو سند حقوقی است.
            </p>
          </section>

          {/* Upload Cards Grid: Clean, Minimal Document Slots */}
          <section className="mb-6 rounded-[32px] p-6 sm:p-8 glass-surface shadow-lg border border-white/90 relative overflow-hidden">
            <div className="flex flex-col lg:flex-row items-center justify-between gap-6 pb-6 border-b border-[#E8E4DB]/70">
              {/* Document Pair */}
              <div className="flex items-center gap-3 w-full lg:w-auto justify-between lg:justify-start">
                <div className="flex items-center gap-2.5 p-3 rounded-2xl bg-white border border-[#E8E4DB]/80 shadow-sm">
                  <div className="w-9 h-9 rounded-xl bg-[#E8EFE9] text-[#324235] flex items-center justify-center font-bold text-xs border border-[#D2DFD4]/80">
                    <span className="material-symbols-outlined text-[20px]">description</span>
                  </div>
                  <div className="min-w-0 pr-1">
                    <p className="text-xs font-bold text-[#141A15] truncate max-w-[150px] sm:max-w-[200px]" dir="ltr">
                      {doc1.fileName}
                    </p>
                    <span className="text-[10px] text-[#71756E] block">سند مبنا • ۳ صفحه</span>
                  </div>
                </div>

                <div className="flex flex-col items-center px-3 relative">
                  <div className="w-8 h-8 rounded-full bg-[#F4F7F4] border border-[#ADC4B0] text-[#3D5241] flex items-center justify-center shadow-sm">
                    <span className="material-symbols-outlined text-[18px] animate-pulse">compare_arrows</span>
                  </div>
                </div>

                <div className="flex items-center gap-2.5 p-3 rounded-2xl bg-white border border-[#E8E4DB]/80 shadow-sm">
                  <div className="w-9 h-9 rounded-xl bg-[#E8EFE9] text-[#324235] flex items-center justify-center font-bold text-xs border border-[#D2DFD4]/80">
                    <span className="material-symbols-outlined text-[20px]">description</span>
                  </div>
                  <div className="min-w-0 pr-1">
                    <p className="text-xs font-bold text-[#141A15] truncate max-w-[150px] sm:max-w-[200px]" dir="ltr">
                      {doc2.fileName}
                    </p>
                    <span className="text-[10px] text-[#71756E] block">سند ثانویه • ۳ صفحه</span>
                  </div>
                </div>
              </div>

              {/* Progress SVG Meter */}
              <div className="flex items-center gap-5 w-full lg:w-auto justify-center">
                <div className="relative flex items-center justify-center w-24 h-24">
                  <svg className="w-24 h-24 -rotate-90" viewBox="0 0 100 100">
                    <circle
                      className="text-[#E8EFE9]"
                      cx="50"
                      cy="50"
                      fill="transparent"
                      r="40"
                      stroke="currentColor"
                      strokeWidth="8"
                    />
                    <circle
                      className="text-[#4A634E] transition-all duration-700 ease-out"
                      cx="50"
                      cy="50"
                      fill="transparent"
                      r="40"
                      stroke="currentColor"
                      strokeDasharray="251.2"
                      strokeDashoffset={strokeDashoffset}
                      strokeLinecap="round"
                      strokeWidth="8"
                    />
                  </svg>
                  <div className="absolute flex flex-col items-center justify-center">
                    <span className="text-xl font-extrabold text-[#141A15] font-mono" dir="ltr">
                      {progress}%
                    </span>
                    <span className="text-[9px] text-[#71756E] font-medium">پیشرفت کل</span>
                  </div>
                </div>

                <div className="flex flex-col text-right">
                  <span className="text-xs font-bold text-[#1F2721]">
                    {stepTitles[activeStep] || 'در حال آماده‌سازی...'}
                  </span>
                  <div className="flex items-center gap-1.5 mt-2">
                    <span className="w-2 h-2 rounded-full bg-[#5C7A60] animate-ping"></span>
                    <span className="text-[10px] text-[#3D5241] font-semibold">
                      {statusMessage}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Horizontal Progress Bar with English Numbers */}
            <div className="mt-5 pt-4 border-t border-[#E8E4DB]/60">
              <div className="flex items-center justify-between text-xs text-[#71756E] mb-1.5 font-mono" dir="ltr">
                <span>0%</span>
                <span className="font-bold text-[#3D5241] text-xs">{progress}%</span>
                <span>100%</span>
              </div>
              <div className="w-full bg-[#E8EFE9] h-2.5 rounded-full overflow-hidden p-0.5 border border-[#D2DFD4]/70">
                <div
                  className="h-full bg-gradient-to-r from-[#4A634E] to-[#5C7A60] rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>

            {/* 5 Step Indicator Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-3 my-6">
              {/* Step 1 */}
              <div
                className={`p-3 rounded-2xl shadow-sm flex items-center gap-2.5 transition-all ${
                  stepStates[1] === 'completed'
                    ? 'bg-white border border-[#D2DFD4]'
                    : stepStates[1] === 'in_progress'
                    ? 'bg-[#F4F7F4] border-2 border-[#5C7A60]'
                    : 'bg-[#FAF8F4]/60 border border-[#E8E4DB]/70 opacity-60'
                }`}
              >
                <div
                  className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${
                    stepStates[1] === 'completed'
                      ? 'bg-[#E8EFE9] text-[#3D5241]'
                      : stepStates[1] === 'in_progress'
                      ? 'bg-[#4A634E] text-white animate-pulse'
                      : 'bg-[#FAF8F4] text-[#71756E]'
                  }`}
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {stepStates[1] === 'completed'
                      ? 'check'
                      : stepStates[1] === 'in_progress'
                      ? 'autorenew'
                      : 'pending'}
                  </span>
                </div>
                <div className="min-w-0">
                  <span className="text-xs font-bold text-[#141A15] block truncate">
                    ۱. استخراج متن و پرداز...
                  </span>
                  <span
                    className={`text-[10px] ${
                      stepStates[1] === 'completed'
                        ? 'text-[#4A634E] font-medium'
                        : stepStates[1] === 'in_progress'
                        ? 'text-[#3D5241] font-bold'
                        : 'text-[#71756E] font-normal'
                    }`}
                  >
                    {stepStates[1] === 'completed'
                      ? 'تکمیل شده'
                      : stepStates[1] === 'in_progress'
                      ? 'در حال پردازش...'
                      : 'در نوبت اجرا'}
                  </span>
                </div>
              </div>

              {/* Step 2 */}
              <div
                className={`p-3 rounded-2xl shadow-sm flex items-center gap-2.5 transition-all ${
                  stepStates[2] === 'completed'
                    ? 'bg-white border border-[#D2DFD4]'
                    : stepStates[2] === 'in_progress'
                    ? 'bg-[#F4F7F4] border-2 border-[#5C7A60]'
                    : 'bg-[#FAF8F4]/60 border border-[#E8E4DB]/70 opacity-60'
                }`}
              >
                <div
                  className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${
                    stepStates[2] === 'completed'
                      ? 'bg-[#E8EFE9] text-[#3D5241]'
                      : stepStates[2] === 'in_progress'
                      ? 'bg-[#4A634E] text-white animate-pulse'
                      : 'bg-[#FAF8F4] text-[#71756E]'
                  }`}
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {stepStates[2] === 'completed'
                      ? 'check'
                      : stepStates[2] === 'in_progress'
                      ? 'autorenew'
                      : 'pending'}
                  </span>
                </div>
                <div className="min-w-0">
                  <span className="text-xs font-bold text-[#141A15] block truncate">
                    ۲. آماده سازی جستجو...
                  </span>
                  <span
                    className={`text-[10px] ${
                      stepStates[2] === 'completed'
                        ? 'text-[#4A634E] font-medium'
                        : stepStates[2] === 'in_progress'
                        ? 'text-[#3D5241] font-bold'
                        : 'text-[#71756E] font-normal'
                    }`}
                  >
                    {stepStates[2] === 'completed'
                      ? 'تکمیل شده'
                      : stepStates[2] === 'in_progress'
                      ? 'در حال پردازش...'
                      : 'در نوبت اجرا'}
                  </span>
                </div>
              </div>

              {/* Step 3 */}
              <div
                className={`p-3 rounded-2xl shadow-sm flex items-center gap-2.5 transition-all ${
                  stepStates[3] === 'completed'
                    ? 'bg-white border border-[#D2DFD4]'
                    : stepStates[3] === 'in_progress'
                    ? 'bg-[#F4F7F4] border-2 border-[#5C7A60]'
                    : 'bg-[#FAF8F4]/60 border border-[#E8E4DB]/70 opacity-60'
                }`}
              >
                <div
                  className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${
                    stepStates[3] === 'completed'
                      ? 'bg-[#E8EFE9] text-[#3D5241]'
                      : stepStates[3] === 'in_progress'
                      ? 'bg-[#4A634E] text-white animate-pulse'
                      : 'bg-[#FAF8F4] text-[#71756E]'
                  }`}
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {stepStates[3] === 'completed'
                      ? 'check'
                      : stepStates[3] === 'in_progress'
                      ? 'autorenew'
                      : 'pending'}
                  </span>
                </div>
                <div className="min-w-0">
                  <span className="text-xs font-bold text-[#141A15] block truncate">
                    ۳. جستجوی معنایی و...
                  </span>
                  <span
                    className={`text-[10px] ${
                      stepStates[3] === 'completed'
                        ? 'text-[#4A634E] font-medium'
                        : stepStates[3] === 'in_progress'
                        ? 'text-[#3D5241] font-bold'
                        : 'text-[#71756E] font-normal'
                    }`}
                  >
                    {stepStates[3] === 'completed'
                      ? 'تکمیل شده'
                      : stepStates[3] === 'in_progress'
                      ? 'در حال پردازش...'
                      : 'در نوبت اجرا'}
                  </span>
                </div>
              </div>

              {/* Step 4 */}
              <div
                className={`p-3 rounded-2xl shadow-sm flex items-center gap-2.5 transition-all ${
                  stepStates[4] === 'completed'
                    ? 'bg-white border border-[#D2DFD4]'
                    : stepStates[4] === 'in_progress'
                    ? 'bg-[#F4F7F4] border-2 border-[#5C7A60]'
                    : 'bg-[#FAF8F4]/60 border border-[#E8E4DB]/70 opacity-60'
                }`}
              >
                <div
                  className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${
                    stepStates[4] === 'completed'
                      ? 'bg-[#E8EFE9] text-[#3D5241]'
                      : stepStates[4] === 'in_progress'
                      ? 'bg-[#4A634E] text-white animate-pulse'
                      : 'bg-[#FAF8F4] text-[#71756E]'
                  }`}
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {stepStates[4] === 'completed'
                      ? 'check'
                      : stepStates[4] === 'in_progress'
                      ? 'autorenew'
                      : 'pending'}
                  </span>
                </div>
                <div className="min-w-0">
                  <span className="text-xs font-bold text-[#141A15] block truncate">۴. پردازش llm</span>
                  <span
                    className={`text-[10px] ${
                      stepStates[4] === 'completed'
                        ? 'text-[#4A634E] font-medium'
                        : stepStates[4] === 'in_progress'
                        ? 'text-[#3D5241] font-bold'
                        : 'text-[#71756E] font-normal'
                    }`}
                  >
                    {stepStates[4] === 'completed'
                      ? 'تکمیل شده'
                      : stepStates[4] === 'in_progress'
                      ? 'در حال پردازش...'
                      : 'در نوبت اجرا'}
                  </span>
                </div>
              </div>

              {/* Step 5 */}
              <div
                className={`p-3 rounded-2xl shadow-sm flex items-center gap-2.5 transition-all ${
                  stepStates[5] === 'completed'
                    ? 'bg-white border border-[#D2DFD4]'
                    : stepStates[5] === 'in_progress'
                    ? 'bg-[#F4F7F4] border-2 border-[#5C7A60]'
                    : 'bg-[#FAF8F4]/60 border border-[#E8E4DB]/70 opacity-60'
                }`}
              >
                <div
                  className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${
                    stepStates[5] === 'completed'
                      ? 'bg-[#E8EFE9] text-[#3D5241]'
                      : stepStates[5] === 'in_progress'
                      ? 'bg-[#4A634E] text-white animate-pulse'
                      : 'bg-[#FAF8F4] text-[#71756E]'
                  }`}
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {stepStates[5] === 'completed'
                      ? 'check'
                      : stepStates[5] === 'in_progress'
                      ? 'autorenew'
                      : 'pending'}
                  </span>
                </div>
                <div className="min-w-0">
                  <span className="text-xs font-bold text-[#141A15] block truncate" title="۵. آماده سازی گزارش و کامپایل اسناد">
                    ۵. آماده‌سازی و کامپایل
                  </span>
                  <span
                    className={`text-[10px] ${
                      stepStates[5] === 'completed'
                        ? 'text-[#4A634E] font-medium'
                        : stepStates[5] === 'in_progress'
                        ? 'text-[#3D5241] font-bold'
                        : 'text-[#71756E] font-normal'
                    }`}
                  >
                    {stepStates[5] === 'completed'
                      ? 'تکمیل شده'
                      : stepStates[5] === 'in_progress'
                      ? 'در حال کامپایل...'
                      : 'در نوبت اجرا'}
                  </span>
                </div>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
};

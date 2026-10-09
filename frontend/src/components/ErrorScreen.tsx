import React from 'react';
import { motion } from 'motion/react';
import { DocumentInfo } from '../types';

interface ErrorScreenProps {
  doc1?: DocumentInfo | null;
  doc2?: DocumentInfo | null;
  errorMessage?: string;
  runId?: string | null;
  failedStep?: number;
  progress?: number;
  statusMessage?: string;
  onRetry: () => void;
  onBackToUpload: () => void;
  onOpenSidebar?: () => void;
}

const ERROR_STEPS = [
  {
    id: 1,
    title: 'استخراج متن و پردازش اولیه اسناد',
    short: '۱. استخراج متن و پرداز...',
    description: 'بارگذاری بافت اسناد و ساختاردهی اولیه',
  },
  {
    id: 2,
    title: 'آماده‌سازی جستجو و پایگاه برداری',
    short: '۲. آماده سازی جستجو...',
    description: 'اینکس‌گذاری برداری و آماده‌سازی موتور بازیابی ترکیبی',
  },
  {
    id: 3,
    title: 'جستجوی معنایی و تطبیق مواد قانونی',
    short: '۳. جستجوی معنایی و...',
    description: 'بازیابی و تطبیق مواد متناظر (Semantic + BM25)',
  },
  {
    id: 4,
    title: 'پردازش و تحلیل هوش مصنوعی (LLM)',
    short: '۴. پردازش llm',
    description: 'تحلیل روابط حقوقی و تضادیابی با مدل زبانی هوشمند',
  },
  {
    id: 5,
    title: 'آماده‌سازی گزارش نهایی و کامپایل اسناد',
    short: '۵. آماده سازی گزارش ن...',
    description: 'دریافت ساختار و کامپایل متون اسناد جهت نمایش گزارش',
  },
];

export const ErrorScreen: React.FC<ErrorScreenProps> = ({
  doc1,
  doc2,
  errorMessage,
  runId,
  failedStep = 3,
  progress,
  statusMessage,
  onRetry,
  onBackToUpload,
}) => {
  const currentFailedStep = Math.max(1, Math.min(5, failedStep));
  const activeStepInfo =
    ERROR_STEPS.find((s) => s.id === currentFailedStep) || ERROR_STEPS[2];

  const defaultProgressMap: Record<number, number> = {
    1: 25,
    2: 50,
    3: 68,
    4: 88,
    5: 95,
  };

  const displayProgress = Math.max(
    1,
    Math.min(
      100,
      typeof progress === 'number' && !isNaN(progress)
        ? progress
        : defaultProgressMap[currentFailedStep] || 68
    )
  );

  // Circumference for r=40 is 2 * PI * 40 ≈ 251.2
  const strokeDashoffset = 251.2 - (251.2 * displayProgress) / 100;

  return (
    <div className="relative min-h-screen w-full flex flex-col justify-between overflow-x-hidden bg-[#f7f3ec] text-[#1c1c18]">
      {/* Main Container */}
      <main className="flex-1 w-full max-w-5xl mx-auto px-6 py-8 md:py-10 flex flex-col justify-center">
        <div className="w-full flex-1 flex flex-col justify-center my-auto">
          {/* Error Hero */}
          <section className="text-center mb-9">
            <h1 className="text-2xl sm:text-3xl lg:text-4xl font-extrabold text-[#141A15] tracking-tight flex items-center justify-center gap-3">
              <span className="text-amber-600 text-3xl sm:text-4xl">⚠️</span>
              <span>به مشکل خوردیم :(</span>
            </h1>
            <p className="mt-3 text-sm text-[#71756E] max-w-2xl mx-auto font-normal leading-relaxed">
              {errorMessage || 'سرور به مشکل خورده است. چند دقیقه بعد مجدداً تلاش کنید.'}
            </p>
          </section>

          {/* Stopped Status Card */}
          <section className="mb-8 rounded-[32px] p-6 sm:p-8 bg-white/90 backdrop-blur-md shadow-lg border border-[#E8E4DB]/80 relative overflow-hidden">
            <div className="flex flex-col lg:flex-row items-center justify-between gap-6 pb-6 border-b border-[#E8E4DB]/70">
              {/* Document Pair & Pause Icon */}
              <div className="flex items-center gap-3 w-full lg:w-auto justify-between lg:justify-start">
                <div className="flex items-center gap-2.5 p-3 rounded-2xl bg-white border border-[#E8E4DB]/80 shadow-sm">
                  <div className="w-9 h-9 rounded-xl bg-[#E8EFE9] text-[#324235] flex items-center justify-center font-bold text-xs border border-[#D2DFD4]/80">
                    <span className="material-symbols-outlined text-[20px]">description</span>
                  </div>
                  <div className="min-w-0 pr-1">
                    <p className="text-xs font-bold text-[#141A15] truncate max-w-[150px] sm:max-w-[200px]" dir="ltr">
                      {doc1?.fileName || doc1?.title || 'سند مبنا'}
                    </p>
                    <span className="text-[10px] text-[#71756E] block">سند مبنا</span>
                  </div>
                </div>

                <div className="flex flex-col items-center px-3 relative">
                  <div className="w-8 h-8 rounded-full bg-amber-50 border border-amber-300 text-amber-700 flex items-center justify-center shadow-sm">
                    <span className="material-symbols-outlined text-[18px]">pause</span>
                  </div>
                  <span className="text-[9px] font-bold text-amber-800 mt-1">فرآیند متوقف شده</span>
                </div>

                <div className="flex items-center gap-2.5 p-3 rounded-2xl bg-white border border-[#E8E4DB]/80 shadow-sm">
                  <div className="w-9 h-9 rounded-xl bg-[#E8EFE9] text-[#324235] flex items-center justify-center font-bold text-xs border border-[#D2DFD4]/80">
                    <span className="material-symbols-outlined text-[20px]">description</span>
                  </div>
                  <div className="min-w-0 pr-1">
                    <p className="text-xs font-bold text-[#141A15] truncate max-w-[150px] sm:max-w-[200px]" dir="ltr">
                      {doc2?.fileName || doc2?.title || 'سند ثانویه'}
                    </p>
                    <span className="text-[10px] text-[#71756E] block">سند ثانویه</span>
                  </div>
                </div>
              </div>

              {/* Progress SVG Meter (Stopped at displayProgress with English numbers) */}
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
                      className="text-[#d97706]"
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
                      {displayProgress}%
                    </span>
                    <span className="text-[9px] text-amber-800 font-medium" dir="ltr">
                      متوقف در {displayProgress}%
                    </span>
                  </div>
                </div>

                <div className="flex flex-col text-right">
                  <span className="text-xs font-bold text-[#1F2721]">
                    متوقف شده در مرحله {currentFailedStep}: {activeStepInfo.title}
                  </span>
                  <div className="flex items-center gap-1.5 mt-2">
                    <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
                    <span className="text-[10px] text-amber-800 font-semibold">
                      {errorMessage || statusMessage || activeStepInfo.description}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Horizontal Progress Bar with English Numbers */}
            <div className="mt-5 pt-4 border-t border-[#E8E4DB]/60">
              <div className="flex items-center justify-between text-xs text-[#71756E] mb-1.5 font-mono" dir="ltr">
                <span>0%</span>
                <span className="font-bold text-amber-800 text-xs">{displayProgress}%</span>
                <span>100%</span>
              </div>
              <div className="w-full bg-[#E8EFE9] h-2.5 rounded-full overflow-hidden p-0.5 border border-[#D2DFD4]/70">
                <div
                  className="h-full bg-gradient-to-r from-amber-500 to-amber-600 rounded-full transition-all duration-500"
                  style={{ width: `${displayProgress}%` }}
                />
              </div>
            </div>

            {/* 5 Steps Indicator Cards - Dynamically updated for the failed stage */}
            <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-3 my-6">
              {ERROR_STEPS.map((step) => {
                const isCompleted = step.id < currentFailedStep;
                const isFailed = step.id === currentFailedStep;

                if (isCompleted) {
                  return (
                    <div
                      key={step.id}
                      className="p-3 rounded-2xl bg-white border border-[#D2DFD4] shadow-sm flex items-center gap-2.5"
                    >
                      <div className="w-7 h-7 rounded-xl bg-[#E8EFE9] text-[#3D5241] flex items-center justify-center shrink-0">
                        <span className="material-symbols-outlined text-[16px]">check</span>
                      </div>
                      <div className="min-w-0">
                        <span
                          className="text-xs font-bold text-[#141A15] block truncate"
                          title={step.title}
                        >
                          {step.short}
                        </span>
                        <span className="text-[10px] text-[#4A634E] font-medium">تکمیل شده</span>
                      </div>
                    </div>
                  );
                }

                if (isFailed) {
                  return (
                    <div
                      key={step.id}
                      className="p-3 rounded-2xl bg-amber-50/80 border-2 border-amber-400 shadow-sm flex items-center gap-2.5 relative ring-2 ring-amber-300/30"
                    >
                      <div className="w-7 h-7 rounded-xl bg-amber-500 text-white flex items-center justify-center shrink-0 animate-pulse">
                        <span className="material-symbols-outlined text-[16px]">priority_high</span>
                      </div>
                      <div className="min-w-0">
                        <span
                          className="text-xs font-bold text-[#141A15] block truncate"
                          title={step.title}
                        >
                          {step.short}
                        </span>
                        <span className="text-[10px] text-amber-800 font-bold">متوقف شده در این مرحله</span>
                      </div>
                    </div>
                  );
                }

                return (
                  <div
                    key={step.id}
                    className="p-3 rounded-2xl bg-[#FAF8F4]/60 border border-[#E8E4DB]/70 flex items-center gap-2.5 opacity-60"
                  >
                    <div className="w-7 h-7 rounded-xl bg-[#FAF8F4] text-[#71756E] flex items-center justify-center shrink-0">
                      <span className="material-symbols-outlined text-[16px]">pending</span>
                    </div>
                    <div className="min-w-0">
                      <span
                        className="text-xs font-bold text-[#71756E] block truncate"
                        title={step.title}
                      >
                        {step.short}
                      </span>
                      <span className="text-[10px] text-[#71756E] font-normal">در نوبت اجرا</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Action Buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            {/* Primary Action Button: تلاش مجدد برای تحلیل */}
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={onRetry}
              className="px-8 py-3.5 rounded-2xl bg-[#27422e] hover:bg-[#1f2721] text-white font-bold text-xs sm:text-sm shadow-md transition-all flex items-center gap-2 cursor-pointer"
            >
              <span className="material-symbols-outlined text-[18px]">cached</span>
              <span>تلاش مجدد برای تحلیل</span>
            </motion.button>

            {/* Secondary Action Button: بازگشت به بارگذاری اسناد */}
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={onBackToUpload}
              className="px-8 py-3.5 rounded-2xl bg-white border border-[#E8E4DB] hover:bg-[#FAF8F4] text-[#141A15] font-bold text-xs sm:text-sm shadow-sm transition-all flex items-center gap-2 cursor-pointer"
            >
              <span>بازگشت به بارگذاری اسناد</span>
              <span className="material-symbols-outlined text-[18px]">arrow_back</span>
            </motion.button>
          </div>

          <p className="text-[11px] text-[#71756E] text-center mt-3">
            فرآیند تحلیل از مرحله {currentFailedStep} ({activeStepInfo.title}) ادامه خواهد یافت
          </p>
        </div>
      </main>
    </div>
  );
};

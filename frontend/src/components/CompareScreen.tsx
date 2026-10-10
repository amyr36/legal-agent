import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Relation, DocumentInfo, Clause } from '../types';

interface CompareScreenProps {
  doc1?: DocumentInfo | null;
  doc2?: DocumentInfo | null;
  clausesDoc1?: Clause[];
  clausesDoc2?: Clause[];
  relations?: Record<string, Relation>;
  analysisId?: number | null;
  onOpenSidebar?: () => void;
}

export const CompareScreen: React.FC<CompareScreenProps> = ({
  doc1,
  doc2,
  clausesDoc1,
  clausesDoc2,
  relations,
  analysisId,
}) => {
  const activeRelationsMap = relations || {};
  const initialKey = Object.keys(activeRelationsMap)[0] || '';

  const [activeRelationKey, setActiveRelationKey] = useState<string>(initialKey);
  const [isRelationsDrawerOpen, setIsRelationsDrawerOpen] = useState(false);
  const [filterCategory, setFilterCategory] = useState<'all' | 'conflict' | 'similarity'>('all');

  const docAContainerRef = useRef<HTMLDivElement>(null);
  const docBContainerRef = useRef<HTMLDivElement>(null);

  // Sync activeRelationKey when analysisId or relations map changes
  useEffect(() => {
    const keys = Object.keys(activeRelationsMap);
    if (keys.length > 0) {
      if (!activeRelationsMap[activeRelationKey] || analysisId) {
        setActiveRelationKey(keys[0]);
      }
    } else {
      setActiveRelationKey('');
    }
  }, [analysisId, relations]);

  const activeRelation: Relation | null =
    activeRelationsMap[activeRelationKey] ||
    (initialKey ? activeRelationsMap[initialKey] : null) ||
    Object.values(activeRelationsMap)[0] ||
    null;

  const relationList = Object.values(activeRelationsMap);
  const relationKeys = Object.keys(activeRelationsMap);
  const currentRelIndex = relationKeys.indexOf(activeRelationKey);

  const scrollContainerToElement = (
    container: HTMLElement | null,
    targetId?: string,
    backendId?: number
  ) => {
    if (!container) return;
    let targetEl: HTMLElement | null = null;
    if (targetId) {
      targetEl =
        container.querySelector(`#${targetId}`) ||
        container.querySelector(`[data-clause-id="${targetId}"]`);
      if (!targetEl) {
        const byDoc = document.getElementById(targetId);
        if (byDoc && container.contains(byDoc)) {
          targetEl = byDoc;
        }
      }
    }
    if (!targetEl && backendId !== undefined) {
      targetEl = container.querySelector(`[data-backend-id="${backendId}"]`);
    }

    if (targetEl && container.contains(targetEl)) {
      const containerRect = container.getBoundingClientRect();
      const targetRect = targetEl.getBoundingClientRect();
      const relativeTop = targetRect.top - containerRect.top + container.scrollTop;
      const targetScrollTop = Math.max(
        0,
        relativeTop - containerRect.height / 2 + targetRect.height / 2
      );
      container.scrollTo({ top: targetScrollTop, behavior: 'smooth' });

      // Visual focus pulse animation
      targetEl.classList.remove('clause-active-pulse');
      void targetEl.offsetWidth; // trigger reflow
      targetEl.classList.add('clause-active-pulse');
    }
  };

  const scrollToClause = (
    targetAId?: string,
    targetBId?: string,
    sourceId?: number,
    targetId?: number
  ) => {
    scrollContainerToElement(docAContainerRef.current, targetAId, sourceId);
    scrollContainerToElement(docBContainerRef.current, targetBId, targetId);
  };

  const handleSelectRelation = (key: string) => {
    if (!activeRelationsMap[key]) return;
    setActiveRelationKey(key);
    const rel = activeRelationsMap[key];
    if (rel) {
      scrollToClause(rel.targetDocA, rel.targetDocB, rel.sourceId, rel.targetId);
    }
  };

  const handlePrevRelation = () => {
    if (relationKeys.length <= 1) return;
    const prevIndex = (currentRelIndex - 1 + relationKeys.length) % relationKeys.length;
    handleSelectRelation(relationKeys[prevIndex]);
  };

  const handleNextRelation = () => {
    if (relationKeys.length <= 1) return;
    const nextIndex = (currentRelIndex + 1) % relationKeys.length;
    handleSelectRelation(relationKeys[nextIndex]);
  };

  const handleClauseClick = (clause: Clause, side: 'A' | 'B') => {
    // Find all relations that involve this clause
    const matches = Object.values(activeRelationsMap).filter((r) => {
      if (side === 'A') {
        return (
          r.targetDocA === clause.id ||
          r.key === clause.id ||
          (clause.backendId !== undefined && r.sourceId === clause.backendId) ||
          (r.sourceId !== undefined && String(r.sourceId) === clause.id)
        );
      } else {
        return (
          r.targetDocB === clause.id ||
          r.key === clause.id ||
          (clause.backendId !== undefined && r.targetId === clause.backendId) ||
          (r.targetId !== undefined && String(r.targetId) === clause.id)
        );
      }
    });

    if (matches.length > 0) {
      const currentIndex = matches.findIndex((m) => m.key === activeRelationKey);
      const nextRelation =
        currentIndex !== -1 && currentIndex < matches.length - 1
          ? matches[currentIndex + 1]
          : matches[0];
      handleSelectRelation(nextRelation.key);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsRelationsDrawerOpen(false);
      } else if (e.key === 'ArrowLeft') {
        handleNextRelation();
      } else if (e.key === 'ArrowRight') {
        handlePrevRelation();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeRelationKey, relationKeys]);

  const filteredRelations = relationList.filter((item) => {
    if (filterCategory === 'all') return true;
    return item.category === filterCategory;
  });

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#f7f3ec] text-[#1c1c18] select-none">
      {/* Main App Workspace */}
      <main className="w-full h-screen flex flex-col pt-14 md:pt-16 pb-3 px-4 sm:px-10 md:px-16 lg:px-20 overflow-hidden relative max-w-5xl mx-auto">
        {/* Top Analysis Header Info */}
        <div className="flex items-center justify-between pb-2 px-1 text-xs">
          <div className="flex items-center gap-2">
            {analysisId && (
              <span className="font-mono text-[11px] font-bold text-[#3e5a44] bg-[#e8efe9] px-2.5 py-0.5 rounded-xl border border-[#d2dfd4]">
                تحلیل #{Math.ceil(analysisId / 2)}
              </span>
            )}
          </div>

          {(doc1?.date || doc2?.date) && (
            <div className="flex items-center gap-1.5 text-[11px] text-[#737972]">
              <span className="material-symbols-outlined text-[14px]">calendar_today</span>
              <span>{doc1?.date || doc2?.date}</span>
            </div>
          )}
        </div>

        {/* Dual Corresponding Documents (Symmetric Two-Column Central Stage) */}
        <div className="w-full flex-1 grid grid-cols-1 md:grid-cols-2 gap-5 min-h-0 items-stretch relative">
          {/* Document 1 (سند اول - نسخه مبنا - سمت راست در RTL) */}
          <section className="flex flex-col rounded-3xl bg-white border border-[#e6e2da] shadow-sm overflow-hidden h-full relative">
            {/* Header Badge */}
            <div className="px-6 py-3.5 flex items-center justify-between border-b border-[#ece8e1]/80 bg-white sticky top-0 z-10">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-bold bg-[#f1ede6] text-[#1c1c18] border border-[#e6e2da] tracking-tight shadow-xs">
                  <span className="w-2 h-2 rounded-full bg-[#3e5a44]/80"></span>
                  سند اول
                </span>
              </div>
              <span
                className="text-[11px] font-medium text-[#737972] bg-[#fdf9f2] px-2.5 py-1 rounded-lg border border-[#e6e2da] max-w-[180px] sm:max-w-[260px] truncate"
                title={doc1?.fileName || 'قرارداد-مشارکت-ساخت-پایه.pdf'}
                dir="ltr"
              >
                {doc1?.fileName || 'قرارداد-مشارکت-ساخت-پایه.pdf'}
              </span>
            </div>

            {/* Document 1 Content Area */}
            <div
              ref={docAContainerRef}
              className="flex-1 overflow-y-auto px-6 sm:px-7 py-6 pb-36 space-y-6 text-[#1c1c18] text-[13px] leading-relaxed text-right"
              id="docViewerA"
            >
              {clausesDoc1 && clausesDoc1.length > 0 ? (
                clausesDoc1.map((clause) => {
                  const isMatch =
                    activeRelation &&
                    (activeRelation.targetDocA === clause.id ||
                      activeRelation.key === clause.id ||
                      (clause.backendId !== undefined && activeRelation.sourceId === clause.backendId) ||
                      (activeRelation.sourceId !== undefined && String(activeRelation.sourceId) === clause.id));
                  const isConflict = activeRelation?.category === 'conflict';
                  const hasRelation = Boolean(clause.relationType);
                  const isClauseConflict = clause.relationType === 'conflict';

                  return (
                    <div
                      key={clause.id}
                      id={clause.id}
                      data-clause-id={clause.id}
                      data-backend-id={clause.backendId}
                      onClick={() => handleClauseClick(clause, 'A')}
                      className={`p-4 rounded-2xl transition-all cursor-pointer ${
                        isMatch
                          ? isConflict
                            ? 'clause-highlight-conflict ring-2 ring-[#d9534f]/30'
                            : 'clause-highlight-similarity ring-2 ring-[#3e5a44]/20'
                          : hasRelation
                          ? isClauseConflict
                            ? 'bg-[#fffcfc] border-r-2 border-[#d9534f]/60 hover:bg-[#fff5f5]'
                            : 'bg-[#fcfdfc] border-r-2 border-[#3e5a44]/60 hover:bg-[#f4f7f4]'
                          : 'hover:bg-[#FAF8F4]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
                        <h3 className="font-bold text-[13px] text-[#1c1c18] flex items-center gap-1.5">
                          <span
                            className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                              isMatch
                                ? isConflict
                                  ? 'bg-[#d9534f]'
                                  : 'bg-[#3e5a44]'
                                : hasRelation
                                ? isClauseConflict
                                  ? 'bg-[#d9534f]/80'
                                  : 'bg-[#3e5a44]/80'
                                : 'bg-[#737972]'
                            }`}
                          />
                          <span>{clause.title}</span>
                        </h3>
                        {hasRelation && (
                          <span
                            className={`text-[10px] font-medium px-2 py-0.5 rounded-full shrink-0 ${
                              isClauseConflict
                                ? 'bg-[#fde8e8] text-[#c53030]'
                                : 'bg-[#e8efe9] text-[#2f5e37]'
                            }`}
                          >
                            {isClauseConflict ? 'تعارض یافته‌شده' : 'مشابهت / تطابق'}
                          </span>
                        )}
                      </div>
                      <div className="space-y-2 text-justify text-[#1c1c18] text-[12.5px] leading-7">
                        {clause.content.map((p, idx) => (
                          <p key={idx} className="text-[#424842]">
                            {p}
                          </p>
                        ))}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="flex flex-col items-center justify-center py-20 text-center text-[#71756E]">
                  <span className="material-symbols-outlined text-[36px] mb-2 text-[#ADC4B0]">description</span>
                  <p className="text-xs font-semibold">متنی برای این سند یافت نشد یا در انتظار دریافت ساختار است.</p>
                </div>
              )}
            </div>
          </section>

          {/* Document 2 (سند دوم - نسخه مؤخر - سمت چپ در RTL) */}
          <section className="flex flex-col rounded-3xl bg-white border border-[#e6e2da] shadow-sm overflow-hidden h-full relative">
            {/* Header Badge */}
            <div className="px-6 py-3.5 flex items-center justify-between border-b border-[#ece8e1]/80 bg-white sticky top-0 z-10">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-bold bg-[#3e5a44] text-white tracking-tight shadow-xs">
                  <span className="w-2 h-2 rounded-full bg-white"></span>
                  سند دوم
                </span>
              </div>
              <span
                className="text-[11px] font-medium text-[#3e5a44] bg-[#e8efe9]/60 px-2.5 py-1 rounded-lg border border-[#3e5a44]/20 max-w-[180px] sm:max-w-[260px] truncate"
                title={doc2?.fileName || 'الحاقیه-شماره-یک-تعدیل-سود.pdf'}
                dir="ltr"
              >
                {doc2?.fileName || 'الحاقیه-شماره-یک-تعدیل-سود.pdf'}
              </span>
            </div>

            {/* Document 2 Content Area */}
            <div
              ref={docBContainerRef}
              className="flex-1 overflow-y-auto px-6 sm:px-7 py-6 pb-36 space-y-6 text-[#1c1c18] text-[13px] leading-relaxed text-right"
              id="docViewerB"
            >
              {clausesDoc2 && clausesDoc2.length > 0 ? (
                clausesDoc2.map((clause) => {
                  const isMatch =
                    activeRelation &&
                    (activeRelation.targetDocB === clause.id ||
                      activeRelation.key === clause.id ||
                      (clause.backendId !== undefined && activeRelation.targetId === clause.backendId) ||
                      (activeRelation.targetId !== undefined && String(activeRelation.targetId) === clause.id));
                  const isConflict = activeRelation?.category === 'conflict';
                  const hasRelation = Boolean(clause.relationType);
                  const isClauseConflict = clause.relationType === 'conflict';

                  return (
                    <div
                      key={clause.id}
                      id={clause.id}
                      data-clause-id={clause.id}
                      data-backend-id={clause.backendId}
                      onClick={() => handleClauseClick(clause, 'B')}
                      className={`p-4 rounded-2xl transition-all cursor-pointer ${
                        isMatch
                          ? isConflict
                            ? 'clause-highlight-conflict ring-2 ring-[#d9534f]/30'
                            : 'clause-highlight-similarity ring-2 ring-[#3e5a44]/20'
                          : hasRelation
                          ? isClauseConflict
                            ? 'bg-[#fffcfc] border-r-2 border-[#d9534f]/60 hover:bg-[#fff5f5]'
                            : 'bg-[#fcfdfc] border-r-2 border-[#3e5a44]/60 hover:bg-[#f4f7f4]'
                          : 'hover:bg-[#FAF8F4]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
                        <h3 className="font-bold text-[13px] text-[#1c1c18] flex items-center gap-1.5">
                          <span
                            className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                              isMatch
                                ? isConflict
                                  ? 'bg-[#d9534f]'
                                  : 'bg-[#3e5a44]'
                                : hasRelation
                                ? isClauseConflict
                                  ? 'bg-[#d9534f]/80'
                                  : 'bg-[#3e5a44]/80'
                                : 'bg-[#737972]'
                            }`}
                          />
                          <span>{clause.title}</span>
                        </h3>
                        {hasRelation && (
                          <span
                            className={`text-[10px] font-medium px-2 py-0.5 rounded-full shrink-0 ${
                              isClauseConflict
                                ? 'bg-[#fde8e8] text-[#c53030]'
                                : 'bg-[#e8efe9] text-[#2f5e37]'
                            }`}
                          >
                            {isClauseConflict ? 'تعارض یافته‌شده' : 'مشابهت / تطابق'}
                          </span>
                        )}
                      </div>
                      <div className="space-y-2 text-justify text-[#1c1c18] text-[12.5px] leading-7">
                        {clause.content.map((p, idx) => (
                          <p key={idx} className="text-[#424842]">
                            {p}
                          </p>
                        ))}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="flex flex-col items-center justify-center py-20 text-center text-[#71756E]">
                  <span className="material-symbols-outlined text-[36px] mb-2 text-[#ADC4B0]">description</span>
                  <p className="text-xs font-semibold">متنی برای این سند یافت نشد یا در انتظار دریافت ساختار است.</p>
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Floating Bottom Overlay (Dock for AI Legal Analysis) */}
        <div className="fixed bottom-3 sm:bottom-4 left-0 right-0 z-30 flex justify-center pointer-events-none px-4 md:px-10 lg:px-16">
          {/* Main Floating Glass Capsule with ultra-compact, clean layout */}
          <div className="relative w-full max-w-5xl pointer-events-auto rounded-2xl bg-white/95 backdrop-blur-2xl border border-white/95 shadow-[0_12px_36px_rgba(20,26,21,0.12),0_4px_12px_rgba(20,26,21,0.05)] py-2.5 px-4 sm:px-5 transition-all duration-300 ring-1 ring-[#3e5a44]/15 text-right">
            {/* Ambient soft glow */}
            <div
              className="absolute -inset-3 -z-10 rounded-[32px] pointer-events-none bg-white/50 backdrop-blur-xl [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_95%)] [-webkit-mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_95%)] opacity-70"
              aria-hidden="true"
            />

            {activeRelation ? (
              <div className="flex flex-col gap-1.5">
                {/* Row 1: Badges & Quick Navigation Controls */}
                <div className="flex items-center justify-between pb-1.5 border-b border-[#ece8e1]/80 gap-2 flex-wrap">
                  {/* Badges */}
                  <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                    <span
                      className={`w-2 h-2 rounded-full shrink-0 ${
                        activeRelation.category === 'conflict'
                          ? 'bg-[#d9534f] ring-2 ring-red-100'
                          : 'bg-[#3e5a44] ring-2 ring-emerald-100'
                      }`}
                    />

                    <span
                      className={`px-2 py-0.5 rounded-md font-bold text-[10.5px] border shadow-2xs ${
                        activeRelation.category === 'conflict'
                          ? 'bg-red-50 text-[#d9534f] border-red-200'
                          : 'bg-[#edf5ee] text-[#3e5a44] border-[#d0e2d3]'
                      }`}
                    >
                      {activeRelation.relation}
                    </span>

                    <span className="px-2 py-0.5 rounded-md font-medium text-[10.5px] bg-[#f7f5f0] text-[#2c332e] border border-[#e6e2da]">
                      {activeRelation.type}
                    </span>

                    {activeRelation.confidence !== undefined && (
                      <span className="px-1.5 py-0.5 rounded-md font-mono font-bold text-[10px] bg-[#E8EFE9] text-[#3D5241]">
                        اطمینان: {Math.round(activeRelation.confidence * 100)}%
                      </span>
                    )}
                  </div>

                  {/* Navigation Prev / Next & List count */}
                  <div className="flex items-center gap-1 shrink-0 mr-auto">
                    {relationKeys.length > 1 && (
                      <span className="text-[10px] text-[#737972] font-mono px-1.5 py-0.5 bg-[#f5f2eb] rounded-md border border-[#e6e2da]">
                        {currentRelIndex + 1} از {relationKeys.length}
                      </span>
                    )}

                    <button
                      type="button"
                      onClick={handlePrevRelation}
                      disabled={relationKeys.length <= 1}
                      className="p-0.5 rounded-md text-[#737972] hover:text-[#1c1c18] hover:bg-[#f1ede6] disabled:opacity-30 disabled:pointer-events-none transition cursor-pointer"
                      title="رابطه قبلی (کلید جهت راست)"
                      aria-label="رابطه قبلی"
                    >
                      <span className="material-symbols-outlined text-[16px]">chevron_right</span>
                    </button>

                    <button
                      type="button"
                      onClick={handleNextRelation}
                      disabled={relationKeys.length <= 1}
                      className="p-0.5 rounded-md text-[#737972] hover:text-[#1c1c18] hover:bg-[#f1ede6] disabled:opacity-30 disabled:pointer-events-none transition cursor-pointer"
                      title="رابطه بعدی (کلید جهت چپ)"
                      aria-label="رابطه بعدی"
                    >
                      <span className="material-symbols-outlined text-[16px]">chevron_left</span>
                    </button>
                  </div>
                </div>

                {/* Row 2: Clean, compact Legal Analysis reasoning text without bulky icon */}
                <p className="text-[#323833] text-[11.5px] leading-relaxed text-justify font-normal m-0 line-clamp-2 hover:line-clamp-none transition-all">
                  {activeRelation.reasoning}
                </p>
              </div>
            ) : (
              <div className="flex items-center justify-between text-xs py-0.5 text-[#71756E]">
                <span>رابطه یا تعارضی برای نمایش یافت نشد.</span>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Right Collapsed Strip Along Right Edge */}
      <aside
        className="fixed top-5 bottom-24 right-3 sm:right-4 md:right-5 z-30 w-13 md:w-14 rounded-3xl bg-white/95 backdrop-blur-md border border-[#e6e2da] shadow-md flex flex-col items-center py-4 px-1 justify-between select-none"
        id="miniTabsStrip"
      >
        {/* Top: Pill showing relation count (Click opens flyout drawer) */}
        <button
          type="button"
          aria-label={`مشاهده ${relationList.length} رابطه کشف‌شده`}
          onClick={() => setIsRelationsDrawerOpen(true)}
          className="flex flex-col items-center cursor-pointer focus:outline-none p-1 rounded-2xl hover:bg-[#f1ede6] transition-colors"
          title={`مشاهده جزئیات ${relationList.length} رابطه`}
        >
          <span className="px-2 py-1 rounded-full bg-[#f1ede6] text-[#1c1c18] font-bold text-[10.5px] border border-[#e6e2da] shadow-xs hover:border-[#3e5a44]/50 transition-colors">
            {relationList.length} مورد
          </span>
        </button>

        {/* Relation Bookmarks: Red #d9534f for conflicts, Olive #3e5a44 for similarities */}
        <div className="flex-1 flex flex-col items-center justify-center gap-3 py-2 w-full">
          {relationList.map((rel, idx) => {
            const isSelected = activeRelationKey === rel.key;
            const isConflict = rel.category === 'conflict';
            return (
              <button
                key={rel.key || rel.id || idx}
                type="button"
                aria-label={`${rel.title}: ${rel.relation}`}
                onClick={(e) => {
                  e.stopPropagation();
                  handleSelectRelation(rel.key);
                }}
                className="relative group cursor-pointer flex items-center justify-center w-full py-1 focus:outline-none"
              >
                <div
                  className={`pill-indicator w-8 md:w-9 h-3 rounded-full ${
                    isConflict ? 'bg-[#d9534f]' : 'bg-[#3e5a44]'
                  } transition-all duration-200 flex items-center justify-center ${
                    isSelected
                      ? `ring-2 ${isConflict ? 'ring-[#d9534f]' : 'ring-[#3e5a44]'} ring-offset-2 ring-offset-[#f7f3ec] scale-110 shadow-sm`
                      : 'opacity-65 shadow-xs group-hover:opacity-100 group-hover:scale-105'
                  }`}
                >
                  <span
                    className={`pill-dot w-1.5 h-1.5 rounded-full ${
                      isSelected ? 'bg-white scale-125' : 'bg-white/70'
                    }`}
                  />
                </div>
                <div className="absolute right-12 whitespace-nowrap bg-[#1c1c18] text-white text-[11px] font-medium py-1.5 px-3 rounded-xl opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity shadow-lg z-50 flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${isConflict ? 'bg-[#d9534f]' : 'bg-[#3e5a44]'}`}
                  />
                  <span>
                    {rel.title} ({rel.type || rel.relation})
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        {/* Bottom Dot */}
        <div className="w-2 h-2 rounded-full bg-[#c2c8c0] opacity-60"></div>
      </aside>

      {/* Expandable Flyout Drawer for Relations */}
      <AnimatePresence>
        {isRelationsDrawerOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsRelationsDrawerOpen(false)}
              className="fixed inset-0 z-40 bg-[#151916]/20 backdrop-blur-[2px] cursor-pointer"
            />

            {/* Flyout Container */}
            <motion.div
              initial={{ x: '100%', opacity: 0.8 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: '100%', opacity: 0.8 }}
              transition={{ type: 'spring', damping: 28, stiffness: 280 }}
              className="fixed top-5 bottom-8 right-3 sm:right-4 md:right-5 z-50 w-[340px] max-w-[calc(100vw-2rem)] rounded-3xl bg-white/95 backdrop-blur-2xl border border-[#e6e2da] shadow-2xl p-4 flex flex-col justify-between text-right"
            >
              <div className="flex flex-col h-full overflow-hidden">
                {/* Header with Title and Close button */}
                <div className="flex items-center justify-between pb-3 mb-2.5 border-b border-[#ece8e1]">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-[13.5px] text-[#1c1c18]">
                      {relationList.length} رابطه کشف‌شده
                    </span>
                  </div>

                  <button
                    type="button"
                    aria-label="بستن نوار روابط"
                    onClick={() => setIsRelationsDrawerOpen(false)}
                    className="flex items-center gap-1 py-1 px-2.5 rounded-xl text-[#737972] hover:text-[#1c1c18] bg-[#f1ede6]/60 hover:bg-[#f1ede6] transition-all text-xs font-semibold group cursor-pointer"
                    title="بستن پنل روابط (Esc)"
                  >
                    <span className="text-[11px] text-[#737972] group-hover:text-[#1c1c18] hidden sm:inline">بستن</span>
                    <span className="material-symbols-outlined text-[18px] group-hover:rotate-90 transition-transform">
                      close
                    </span>
                  </button>
                </div>

                {/* Filter Tabs */}
                <div className="flex items-center gap-1 p-1 bg-[#f1ede6] rounded-2xl mb-3 text-[11px] font-medium text-[#424842] border border-[#ece8e1]">
                  <button
                    type="button"
                    onClick={() => setFilterCategory('all')}
                    className={`flex-1 py-1.5 px-2 rounded-xl transition-all text-center cursor-pointer ${
                      filterCategory === 'all'
                        ? 'bg-white text-[#3e5a44] font-bold shadow-sm'
                        : 'text-[#737972] hover:text-[#1c1c18]'
                    }`}
                  >
                    همه ({relationList.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilterCategory('conflict')}
                    className={`flex-1 py-1.5 px-2 rounded-xl transition-all text-center cursor-pointer ${
                      filterCategory === 'conflict'
                        ? 'bg-white text-[#3e5a44] font-bold shadow-sm'
                        : 'text-[#737972] hover:text-[#1c1c18]'
                    }`}
                  >
                    تناقضات ({relationList.filter((r) => r.category === 'conflict').length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilterCategory('similarity')}
                    className={`flex-1 py-1.5 px-2 rounded-xl transition-all text-center cursor-pointer ${
                      filterCategory === 'similarity'
                        ? 'bg-white text-[#3e5a44] font-bold shadow-sm'
                        : 'text-[#737972] hover:text-[#1c1c18]'
                    }`}
                  >
                    تشابه‌ها ({relationList.filter((r) => r.category === 'similarity').length})
                  </button>
                </div>

                {/* Relations Cards List */}
                <div className="flex-1 overflow-y-auto space-y-2.5 pr-0.5 pl-0.5">
                  {filteredRelations.map((rel) => {
                    const isSelected = activeRelationKey === rel.key;
                    return (
                      <article
                        key={rel.id}
                        onClick={() => handleSelectRelation(rel.key)}
                        className={`p-3.5 rounded-2xl cursor-pointer transition-all border ${
                          isSelected
                            ? 'bg-[#fdf9f2] border-2 border-[#3e5a44]/60 shadow-sm'
                            : 'bg-white hover:bg-[#fdf9f2] border-[#e6e2da]'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="font-bold text-[12px] text-[#1c1c18]">{rel.title}</span>
                          <span
                            className={`px-2 py-0.5 rounded-md text-[10px] font-bold border ${
                              rel.category === 'conflict'
                                ? 'bg-red-50 text-[#d9534f] border-red-200'
                                : 'bg-[#edf5ee] text-[#3e5a44] border-[#d0e2d3]'
                            }`}
                          >
                            {rel.relation}
                          </span>
                        </div>

                        <div className="flex items-center gap-1.5 text-[10.5px] text-[#737972] mb-1">
                          <span>نوع:</span>
                          <span className="text-[#1c1c18] font-medium bg-white px-2 py-0.5 rounded-md border border-[#e6e2da]">
                            {rel.type}
                          </span>
                        </div>

                        <p className="text-[11px] text-[#424842] leading-relaxed">{rel.summary}</p>
                      </article>
                    );
                  })}
                </div>
              </div>

              {/* Footer hint */}
              <div className="pt-3 border-t border-[#ece8e1] text-[10.5px] text-[#737972] flex items-center justify-between">
                <span>برای بستن کلید Esc یا دکمه بستن</span>
                <span className="font-mono text-[9px] bg-[#f1ede6] px-1.5 py-0.5 rounded border border-[#e6e2da]">
                  ESC
                </span>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
};

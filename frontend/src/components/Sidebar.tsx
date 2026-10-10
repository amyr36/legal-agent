import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { User, HistoryItem, AppScreen } from '../types';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onOpen: () => void;
  currentUser: User;
  history: HistoryItem[];
  currentScreen: AppScreen;
  onNavigate: (screen: AppScreen) => void;
  onSelectHistoryItem?: (item: HistoryItem) => void;
  onLogout: () => void;
  isLoadingHistory?: boolean;
  onRefreshHistory?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onClose,
  onOpen,
  currentUser,
  history,
  onNavigate,
  onSelectHistoryItem,
  onLogout,
  isLoadingHistory = false,
  onRefreshHistory,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [loadingItemId, setLoadingItemId] = useState<number | null>(null);

  const filteredHistory = history.filter((item) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.trim().toLowerCase();
    const dispNum = String(item.displayNumber ?? Math.ceil((item.analysisId || 1) / 2));
    return (
      item.title.toLowerCase().includes(q) ||
      (item.doc1Name && item.doc1Name.toLowerCase().includes(q)) ||
      (item.doc2Name && item.doc2Name.toLowerCase().includes(q)) ||
      dispNum.includes(q)
    );
  });

  const handleItemClick = async (item: HistoryItem) => {
    if (item.analysisId) {
      setLoadingItemId(item.analysisId);
    }
    try {
      if (onSelectHistoryItem) {
        await onSelectHistoryItem(item);
      }
    } finally {
      setLoadingItemId(null);
    }
  };
  return (
    <>
      {/* Floating Open Sidebar Trigger (At top-left corner) */}
      {!isOpen && (
        <button
          aria-label="باز کردن منوی کناری"
          onClick={onOpen}
          className="fixed top-5 left-5 z-40 p-2.5 rounded-2xl bg-white/95 backdrop-blur-md shadow-md border border-[#E8E4DB]/80 text-[#1F2721] hover:text-[#3D5241] hover:bg-white hover:scale-105 transition-all duration-200 flex items-center justify-center group cursor-pointer"
          title="باز کردن منو"
        >
          <span className="material-symbols-outlined text-[22px] text-[#324235] group-hover:text-[#4A634E] transition-colors">
            menu
          </span>
        </button>
      )}

      {/* Backdrop Overlay */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-[#141A15]/25 backdrop-blur-sm cursor-pointer"
          />
        )}
      </AnimatePresence>

      {/* Sidebar Content */}
      <AnimatePresence>
        {isOpen && (
          <motion.aside
            initial={{ x: '-100%', opacity: 0.8 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '-100%', opacity: 0.8 }}
            transition={{ type: 'spring', damping: 28, stiffness: 280 }}
            className="fixed inset-y-4 left-4 z-50 w-[275px] rounded-[32px] glass-surface shadow-2xl flex flex-col justify-between p-5 border border-white/90 select-none text-right"
          >
            {/* Top: Logo & Main Navigation */}
            <div className="flex flex-col h-full overflow-hidden">
              {/* Brand Header */}
              <div className="flex items-center justify-between pb-4 mb-4 border-b border-[#E8E4DB]/70">
                <div className="flex items-center gap-3">
                  <div className="relative flex items-center justify-center w-9 h-9 rounded-2xl bg-gradient-to-tr from-[#1F2721] to-[#324235] shadow-md">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#ADC4B0]"></span>
                  </div>
                  <div>
                    <span className="font-extrabold text-[15px] tracking-tight text-[#141A15] block">
                      دادبان هوشمند
                    </span>
                    <span className="text-[10px] font-medium text-[#71756E] block -mt-0.5">
                      داشبورد تحلیلی کارشناس
                    </span>
                  </div>
                </div>

                {/* Close Button */}
                <button
                  aria-label="بستن منو"
                  onClick={onClose}
                  className="text-[#71756E] hover:text-[#1F2721] p-1.5 rounded-xl hover:bg-[#E8EFE9]/60 transition-colors cursor-pointer"
                  title="بستن منو"
                >
                  <span className="material-symbols-outlined text-[20px]">first_page</span>
                </button>
              </div>

              {/* Quick Search Input */}
              <div className="relative mb-4">
                <span className="material-symbols-outlined text-[18px] text-[#71756E] absolute right-3 top-2.5 pointer-events-none">
                  search
                </span>
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="جستجو در تحلیل‌ها..."
                  className="w-full text-xs pr-9 pl-8 py-2 rounded-2xl bg-[#F4F7F4]/80 border border-[#E8E4DB]/50 focus:ring-2 focus:ring-[#5C7A60]/40 focus:border-[#5C7A60] placeholder:text-[#71756E]/80 text-[#1F2721] outline-none transition"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="absolute left-2.5 top-2.5 text-[#71756E] hover:text-[#1F2721] p-0.5 rounded cursor-pointer"
                    title="پاک کردن جستجو"
                  >
                    <span className="material-symbols-outlined text-[14px]">close</span>
                  </button>
                )}
              </div>

              {/* Action Button: New Analysis */}
              <div className="mb-3">
                <button
                  onClick={() => {
                    onNavigate('upload');
                    onClose();
                  }}
                  className="w-full py-2.5 px-3 rounded-2xl bg-[#4A634E] hover:bg-[#3D5241] active:translate-y-0 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-sm transition-all cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">add</span>
                  <span>تحلیل مقایسه‌ای جدید</span>
                </button>
              </div>

              {/* History Section Header */}
              <div className="flex items-center justify-between px-2 mb-2">
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] font-bold text-[#71756E] tracking-wider">
                    تاریخچه تحلیل‌ها
                  </span>
                  {onRefreshHistory && (
                    <button
                      onClick={onRefreshHistory}
                      disabled={isLoadingHistory}
                      className="text-[#71756E] hover:text-[#3D5241] p-0.5 rounded transition cursor-pointer"
                      title="بروزرسانی تاریخچه از سرور"
                    >
                      <span
                        className={`material-symbols-outlined text-[14px] ${
                          isLoadingHistory ? 'animate-spin text-[#4A634E]' : ''
                        }`}
                      >
                        refresh
                      </span>
                    </button>
                  )}
                </div>
                <span className="text-[10px] font-mono text-[#324235] bg-[#E8EFE9] px-2 py-0.5 rounded-full font-semibold">
                  {filteredHistory.length}
                </span>
              </div>

              <nav className="space-y-1 text-xs font-medium flex-1 overflow-y-auto pr-0.5 pl-0.5">
                {isLoadingHistory && filteredHistory.length === 0 ? (
                  <div className="py-8 text-center text-[#71756E] text-[11px]">
                    <span className="w-5 h-5 border-2 border-[#4A634E] border-t-transparent rounded-full animate-spin inline-block mb-2"></span>
                    <span className="block">در حال بارگذاری تاریخچه از سرور...</span>
                  </div>
                ) : filteredHistory.length > 0 ? (
                  <div className="space-y-1.5">
                    {filteredHistory.map((item, index) => {
                      const isLoadingThis = loadingItemId === item.analysisId;
                      return (
                        <button
                          key={item.id}
                          disabled={isLoadingThis}
                          onClick={() => handleItemClick(item)}
                          className={`w-full text-right group block p-2.5 rounded-2xl transition-all cursor-pointer ${
                            isLoadingThis
                              ? 'bg-amber-50/70 border border-amber-300 pointer-events-none'
                              : index === 0
                              ? 'bg-white shadow-sm border border-[#D2DFD4]/90 hover:border-[#5C7A60]'
                              : 'hover:bg-white/70 border border-transparent hover:border-[#E8E4DB]'
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-1 min-w-0">
                            {isLoadingThis ? (
                              <span className="w-4 h-4 border-2 border-[#4A634E] border-t-transparent rounded-full animate-spin shrink-0"></span>
                            ) : (
                              <span
                                className={`material-symbols-outlined text-[16px] shrink-0 transition-colors ${
                                  index === 0 ? 'text-[#4A634E]' : 'text-[#71756E] group-hover:text-[#4A634E]'
                                }`}
                              >
                                article
                              </span>
                            )}
                            <span
                              className={`text-xs leading-snug line-clamp-2 transition-colors ${
                                index === 0
                                  ? 'font-bold text-[#141A15]'
                                  : 'font-semibold text-[#324235] group-hover:text-[#141A15]'
                              }`}
                              title={item.title}
                            >
                              {item.title}
                            </span>
                          </div>
                          <div className="text-[10px] text-[#71756E] pr-6 flex items-center justify-between">
                            <span>{item.formattedDate || item.timeAgo}</span>
                            <span className="text-[10px] text-[#3D5241] bg-[#E8EFE9] px-2 py-0.5 rounded-md font-mono font-bold">
                              تحلیل #{item.displayNumber ?? Math.ceil((item.analysisId || 1) / 2)}
                            </span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className="py-8 text-center text-[#71756E] text-[11px]">
                    <span className="material-symbols-outlined text-[24px] text-[#ADC4B0] block mb-1">
                      {searchQuery ? 'search_off' : 'history'}
                    </span>
                    <span>
                      {searchQuery ? 'موردی با این عبارت یافت نشد' : 'هنوز سابقه‌ای ثبت نشده است'}
                    </span>
                  </div>
                )}
              </nav>
            </div>

            {/* Bottom Profile Info */}
            <div className="pt-4 border-t border-[#E8E4DB]/70 mt-2 flex items-center justify-between">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="w-9 h-9 rounded-2xl bg-gradient-to-tr from-[#1F2721] to-[#3D5241] text-[#E8EFE9] flex items-center justify-center font-bold text-xs shadow shrink-0">
                  {currentUser.initials}
                </div>
                <div className="flex items-center min-w-0">
                  <p className="text-xs font-bold text-[#141A15] truncate">{currentUser.name}</p>
                </div>
              </div>
              <button
                onClick={onLogout}
                aria-label="خروج از حساب"
                className="text-[#71756E] hover:text-[#ba1a1a] p-1.5 rounded-xl hover:bg-red-50 transition-colors cursor-pointer shrink-0"
                title="خروج از حساب"
              >
                <span className="material-symbols-outlined text-[18px]">logout</span>
              </button>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
};

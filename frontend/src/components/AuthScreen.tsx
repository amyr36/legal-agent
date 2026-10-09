import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { LegalApiService } from '../services/api';

interface AuthScreenProps {
  onSuccess: (username: string) => void;
}

export const AuthScreen: React.FC<AuthScreenProps> = ({ onSuccess }) => {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [loading, setLoading] = useState(false);
  
  // Validation and server errors
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [authError, setAuthError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!username.trim()) {
      newErrors.username = 'لطفاً نام کاربری را وارد نمایید.';
    }

    if (!password.trim()) {
      newErrors.password = 'کلمه عبور نمی‌تواند خالی باشد.';
    } else if (password.length < 8) {
      newErrors.password = 'کلمه عبور باید حداقل ۸ کاراکتر باشد.';
    }

    if (mode === 'register') {
      if (!phone.trim()) {
        newErrors.phone = 'شماره تلفن همراه الزامی است.';
      } else if (phone.replace(/\D/g, '').length < 10) {
        newErrors.phone = 'شماره تلفن همراه معتبر نیست (حداقل ۱۰ یا ۱۱ رقم).';
      }

      if (!confirmPassword.trim()) {
        newErrors.confirmPassword = 'تکرار کلمه عبور الزامی است.';
      } else if (confirmPassword !== password) {
        newErrors.confirmPassword = 'تکرار کلمه عبور با کلمه عبور وارد شده مطابقت ندارد.';
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError(null);
    setSuccessMessage(null);

    if (!validate()) {
      return;
    }

    setLoading(true);

    try {
      if (mode === 'login') {
        const user = await LegalApiService.authenticate(username, password);
        setSuccessMessage('ورود با موفقیت انجام شد');
        setTimeout(() => {
          onSuccess(user.name);
        }, 500);
      } else {
        const user = await LegalApiService.register({ username, phone, password });
        setSuccessMessage('ثبت‌نام با موفقیت انجام شد');
        setTimeout(() => {
          onSuccess(user.name);
        }, 500);
      }
    } catch (err: any) {
      setAuthError(err.message || 'خطا در احراز هویت با سرور');
    } finally {
      setLoading(false);
    }
  };

  const handleModeChange = (newMode: 'login' | 'register') => {
    setMode(newMode);
    setErrors({});
    setAuthError(null);
    setSuccessMessage(null);
  };

  return (
    <main className="w-full min-h-screen flex items-center justify-center p-4 bg-[#fdf9f2] text-[#1c1c18] relative select-none">
      <div className="flex flex-col w-full max-w-lg mx-auto">
        <section className="relative w-full py-8 sm:py-12 flex flex-col items-center justify-center">
          {/* Ambient organic depth glow */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-gradient-to-tr from-[#afceb3]/20 via-[#ece8e1]/30 to-transparent rounded-full blur-3xl pointer-events-none -z-10" />

          {/* Top Pill Brand Marker */}
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="inline-flex items-center gap-2 bg-white text-[#3e5a44] px-4 py-1.5 rounded-full shadow-sm mb-6 border border-[#c2c8c0]/40 select-none text-center"
          >
            <span className="w-2.5 h-2.5 rounded-full bg-[#3e5a44] animate-pulse"></span>
            <span className="text-[11.5px] font-semibold text-[#1c1c18]">
              سامانه هوشمند تشخیص تشابه و تناقض در اسناد قوانین تخصصی
            </span>
          </motion.div>

          {/* Header Titles */}
          <div className="text-center mb-6 w-full px-2 min-h-[88px] flex flex-col items-center justify-center">
            <motion.h1
              key={`h1-${mode}`}
              initial={{ opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 }}
              className="text-3xl sm:text-4xl font-extrabold text-[#1c1c18] tracking-tight"
            >
              {mode === 'login' ? 'ورود به حساب کاربری' : 'ایجاد حساب کاربری جدید'}
            </motion.h1>
            <motion.p
              key={`p-${mode}`}
              initial={{ opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18, delay: 0.02 }}
              className="text-sm sm:text-base text-[#5a605c] mt-2 max-w-md mx-auto leading-relaxed"
            >
              {mode === 'login'
                ? 'جهت دسترسی به تاریخچه تحلیل‌ها و استخراج تعارضات، وارد حساب کاربری خود شوید.'
                : 'برای شروع تحلیل تطبیقی و استخراج هوشمند تعارضات اسناد، اطلاعات زیر را وارد کنید.'}
            </motion.p>
          </div>

          {/* Tab Switcher: Gliding White Pill Indicator */}
          <div className="w-full flex items-center justify-center mb-6">
            <div className="relative flex items-center p-1 bg-[#ede8df] rounded-full border border-[#c2c8c0]/40 w-56 select-none shadow-inner">
              {/* Single smooth sliding indicator with hardware-accelerated translateX */}
              <motion.div
                className="absolute top-1 bottom-1 right-1 w-[calc(50%-4px)] bg-white rounded-full shadow-sm pointer-events-none"
                animate={{
                  x: mode === 'login' ? '0%' : '-100%',
                }}
                transition={{ type: 'spring', stiffness: 450, damping: 32 }}
              />

              <button
                type="button"
                onClick={() => handleModeChange('login')}
                className={`relative flex-1 z-10 py-1.5 text-center text-xs font-bold transition-colors cursor-pointer rounded-full ${
                  mode === 'login' ? 'text-[#1c1c18]' : 'text-[#737972] hover:text-[#1c1c18]'
                }`}
              >
                ورود
              </button>

              <button
                type="button"
                onClick={() => handleModeChange('register')}
                className={`relative flex-1 z-10 py-1.5 text-center text-xs font-bold transition-colors cursor-pointer rounded-full ${
                  mode === 'register' ? 'text-[#1c1c18]' : 'text-[#737972] hover:text-[#1c1c18]'
                }`}
              >
                ثبت‌نام
              </button>
            </div>
          </div>

          {/* Global Alert for Auth Error */}
          <AnimatePresence>
            {authError && (
              <motion.div
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                className="w-full mb-4 p-3.5 rounded-2xl bg-red-50 border border-red-200 text-red-700 text-xs font-medium flex items-center gap-2.5"
              >
                <span className="material-symbols-outlined text-[20px] text-red-600">error</span>
                <span>{authError}</span>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Form Container */}
          <form onSubmit={handleSubmit} noValidate className="w-full flex flex-col">
            <div className="flex flex-col gap-4">
              {/* 1. Username / Email Field */}
              <div className="flex flex-col gap-1 text-right">
                <label className="text-xs font-semibold text-[#5a605c] pr-3" htmlFor="username-input">
                  نام کاربری یا ایمیل سازمانی
                </label>
                <div className="relative flex items-center">
                  <input
                    id="username-input"
                    type="text"
                    value={username}
                    onChange={(e) => {
                      setUsername(e.target.value);
                      if (errors.username) setErrors((prev) => ({ ...prev, username: '' }));
                    }}
                    placeholder="username / user@firm.ir"
                    dir="auto"
                    className={`w-full bg-white text-[#1c1c18] text-sm pl-12 pr-5 py-3.5 rounded-full shadow-sm placeholder:text-[#c3c8c3] focus:outline-none transition-all ${
                      errors.username
                        ? 'border-2 border-red-500 focus:ring-2 focus:ring-red-300'
                        : 'border-0 focus:ring-2 focus:ring-[#3e5a44]/30'
                    }`}
                  />
                  <span className="absolute left-4 text-[#5a605c] pointer-events-none flex items-center">
                    <span className="material-symbols-outlined text-[20px]">person</span>
                  </span>
                </div>
                {errors.username && (
                  <p className="text-[11px] text-red-600 pr-3 mt-0.5 font-medium">{errors.username}</p>
                )}
              </div>

              {/* 2. Phone Field (Register Mode Only) */}
              <AnimatePresence initial={false}>
                {mode === 'register' && (
                  <motion.div
                    key="phone-field-wrapper"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="flex flex-col gap-1 text-right pb-1">
                      <label className="text-xs font-semibold text-[#5a605c] pr-3" htmlFor="phone-input">
                        شماره تلفن همراه
                      </label>
                      <div className="relative flex items-center">
                        <input
                          id="phone-input"
                          type="tel"
                          inputMode="tel"
                          value={phone}
                          onChange={(e) => {
                            setPhone(e.target.value);
                            if (errors.phone) setErrors((prev) => ({ ...prev, phone: '' }));
                          }}
                          placeholder="۰۹۱۲۳۴۵۶۷۸۹"
                          dir="ltr"
                          className={`w-full bg-white text-[#1c1c18] text-sm pl-12 pr-5 py-3.5 rounded-full shadow-sm placeholder:text-[#c3c8c3] focus:outline-none transition-all ${
                            errors.phone
                              ? 'border-2 border-red-500 focus:ring-2 focus:ring-red-300'
                              : 'border-0 focus:ring-2 focus:ring-[#3e5a44]/30'
                          }`}
                        />
                        <span className="absolute left-4 text-[#5a605c] pointer-events-none flex items-center">
                          <span className="material-symbols-outlined text-[20px]">smartphone</span>
                        </span>
                      </div>
                      {errors.phone && (
                        <p className="text-[11px] text-red-600 pr-3 mt-0.5 font-medium">{errors.phone}</p>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* 3. Password Field */}
              <div className="flex flex-col gap-1 text-right">
                <label className="text-xs font-semibold text-[#5a605c] pr-3" htmlFor="password-input">
                  کلمه عبور
                </label>
                <div className="relative flex items-center">
                  <input
                    id="password-input"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      if (errors.password) setErrors((prev) => ({ ...prev, password: '' }));
                    }}
                    placeholder="••••••••••••"
                    dir="ltr"
                    className={`w-full bg-white text-[#1c1c18] text-sm pl-12 pr-5 py-3.5 rounded-full shadow-sm placeholder:text-[#c3c8c3] focus:outline-none transition-all ${
                      errors.password
                        ? 'border-2 border-red-500 focus:ring-2 focus:ring-red-300'
                        : 'border-0 focus:ring-2 focus:ring-[#3e5a44]/30'
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute left-4 text-[#5a605c] hover:text-[#1c1c18] transition-colors flex items-center cursor-pointer p-1"
                    title={showPassword ? 'مخفی کردن' : 'نمایش'}
                  >
                    <span className="material-symbols-outlined text-[20px]">
                      {showPassword ? 'visibility_off' : 'visibility'}
                    </span>
                  </button>
                </div>
                {errors.password && (
                  <p className="text-[11px] text-red-600 pr-3 mt-0.5 font-medium">{errors.password}</p>
                )}
              </div>

              {/* 4. Confirm Password Field (Register Mode Only) */}
              <AnimatePresence initial={false}>
                {mode === 'register' && (
                  <motion.div
                    key="confirm-field-wrapper"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="flex flex-col gap-1 text-right pb-1">
                      <label className="text-xs font-semibold text-[#5a605c] pr-3" htmlFor="confirm-password-input">
                        تکرار کلمه عبور
                      </label>
                      <div className="relative flex items-center">
                        <input
                          id="confirm-password-input"
                          type={showConfirmPassword ? 'text' : 'password'}
                          value={confirmPassword}
                          onChange={(e) => {
                            setConfirmPassword(e.target.value);
                            if (errors.confirmPassword) setErrors((prev) => ({ ...prev, confirmPassword: '' }));
                          }}
                          placeholder="••••••••••••"
                          dir="ltr"
                          className={`w-full bg-white text-[#1c1c18] text-sm pl-12 pr-5 py-3.5 rounded-full shadow-sm placeholder:text-[#c3c8c3] focus:outline-none transition-all ${
                            errors.confirmPassword
                              ? 'border-2 border-red-500 focus:ring-2 focus:ring-red-300'
                              : 'border-0 focus:ring-2 focus:ring-[#3e5a44]/30'
                          }`}
                        />
                        <button
                          type="button"
                          onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                          className="absolute left-4 text-[#5a605c] hover:text-[#1c1c18] transition-colors flex items-center cursor-pointer p-1"
                          title={showConfirmPassword ? 'مخفی کردن' : 'نمایش'}
                        >
                          <span className="material-symbols-outlined text-[20px]">
                            {showConfirmPassword ? 'visibility_off' : 'visibility'}
                          </span>
                        </button>
                      </div>
                      {errors.confirmPassword && (
                        <p className="text-[11px] text-red-600 pr-3 mt-0.5 font-medium">{errors.confirmPassword}</p>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* 5. Remember Me (Login Mode Only) */}
              <AnimatePresence initial={false}>
                {mode === 'login' && (
                  <motion.div
                    key="remember-field-wrapper"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="items-center justify-between px-3 py-1 flex">
                      <label className="flex items-center gap-2 cursor-pointer select-none text-[#5a605c] hover:text-[#1c1c18] transition-colors">
                        <input
                          type="checkbox"
                          checked={rememberMe}
                          onChange={(e) => setRememberMe(e.target.checked)}
                          className="w-4 h-4 rounded text-[#3e5a44] focus:ring-[#3e5a44] border-[#c2c8c0] bg-white cursor-pointer"
                        />
                        <span className="text-xs font-medium">مرا به خاطر بسپار</span>
                      </label>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Main CTA Button */}
              <motion.button
                whileHover={{ scale: 1.01 }}
                whileTap={{ scale: 0.99 }}
                type="submit"
                disabled={loading}
                className="w-full bg-[#3e5a44] hover:bg-[#27422e] text-white py-3.5 rounded-full font-bold text-sm shadow-md transition-all duration-300 flex items-center justify-center gap-2 mt-1 cursor-pointer disabled:opacity-75"
              >
                <span>
                  {loading
                    ? 'در حال پردازش...'
                    : successMessage ||
                      (mode === 'login' ? 'ورود به حساب کاربری' : 'ایجاد حساب کاربری')}
                </span>
                <span className="material-symbols-outlined text-[18px] rotate-180">arrow_forward</span>
              </motion.button>

              {/* Bottom Switcher Link */}
              <div className="w-full text-center min-h-[28px] flex items-center justify-center mt-1">
                <p className="text-xs text-[#5a605c]">
                  {mode === 'login' ? (
                    <>
                      حساب کاربری ندارید؟{' '}
                      <button
                        type="button"
                        onClick={() => handleModeChange('register')}
                        className="text-[#27422e] hover:text-[#3e5a44] font-bold transition-colors cursor-pointer mr-1 underline underline-offset-4"
                      >
                        ثبت‌نام کنید
                      </button>
                    </>
                  ) : (
                    <>
                      قبلاً ثبت‌نام کرده‌اید؟{' '}
                      <button
                        type="button"
                        onClick={() => handleModeChange('login')}
                        className="text-[#27422e] hover:text-[#3e5a44] font-bold transition-colors cursor-pointer mr-1 underline underline-offset-4"
                      >
                        وارد شوید
                      </button>
                    </>
                  )}
                </p>
              </div>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
};

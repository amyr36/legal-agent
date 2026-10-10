import { useState, useEffect } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  AppScreen,
  User,
  HistoryItem,
  DocumentInfo,
  Clause,
  Relation,
} from './types';
import {
  LegalApiService,
  registerUnauthorizedHandler,
  transformStructureToClauses,
  formatPersianTimeAgo,
  formatPersianDate,
} from './services/api';
import { Sidebar } from './components/Sidebar';
import { AuthScreen } from './components/AuthScreen';
import { UploadScreen } from './components/UploadScreen';
import { ProcessingScreen } from './components/ProcessingScreen';
import { ErrorScreen } from './components/ErrorScreen';
import { CompareScreen } from './components/CompareScreen';

export default function App() {
  const [currentScreen, setCurrentScreen] = useState<AppScreen>('login');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [currentUser, setCurrentUser] = useState<User>(() => {
    return (
      LegalApiService.getCurrentStoredUser() || {
        id: 'usr_default',
        name: 'کاربر',
        role: 'کارشناس حقوقی',
        email: 'user@example.com',
        initials: 'ک',
      }
    );
  });
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [doc1, setDoc1] = useState<DocumentInfo | null>(null);
  const [doc2, setDoc2] = useState<DocumentInfo | null>(null);
  const [isRetry, setIsRetry] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeAnalysisId, setActiveAnalysisId] = useState<number | null>(null);
  const [lastErrorMessage, setLastErrorMessage] = useState<string>('');
  const [errorDetails, setErrorDetails] = useState<{
    failedStep: number;
    progress: number;
    statusMessage?: string;
  }>({
    failedStep: 3,
    progress: 68,
  });
  
  // Real analysis clauses and relations
  const [clausesDoc1, setClausesDoc1] = useState<Clause[]>([]);
  const [clausesDoc2, setClausesDoc2] = useState<Clause[]>([]);
  const [relations, setRelations] = useState<Record<string, Relation>>({});

  // Function to fetch history from /analyze/history
  const refreshHistory = async () => {
    setIsLoadingHistory(true);
    try {
      const items = await LegalApiService.fetchHistory();
      if (items) {
        setHistory(items);
      }
    } catch (err) {
      console.warn('Error fetching history:', err);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  // Register unauthorized listener to return to login on 401
  useEffect(() => {
    registerUnauthorizedHandler(() => {
      setCurrentScreen('login');
    });

    // Check if already logged in
    const token = LegalApiService.getAuthToken();
    const storedUser = LegalApiService.getCurrentStoredUser();
    if (token && storedUser) {
      setCurrentUser(storedUser);
      setCurrentScreen('upload');
    }
  }, []);

  // Fetch real history whenever user enters non-login screens
  useEffect(() => {
    if (currentScreen !== 'login') {
      refreshHistory();
    }
  }, [currentScreen]);

  const handleAuthSuccess = (name: string) => {
    const updatedUser: User = {
      ...currentUser,
      name,
    };
    setCurrentUser(updatedUser);
    setIsRetry(false);
    setCurrentScreen('upload');
  };

  const handleStartAnalysis = (
    selectedDoc1: DocumentInfo,
    selectedDoc2: DocumentInfo,
    runId?: string
  ) => {
    setDoc1(selectedDoc1);
    setDoc2(selectedDoc2);
    setIsRetry(false);
    setActiveRunId(runId || null);
    setCurrentScreen('processing');
  };

  const handleProcessingComplete = (data: {
    runId: string;
    analysisId?: number | null;
    relations: Record<string, Relation>;
    clausesDoc1: Clause[];
    clausesDoc2: Clause[];
  }) => {
    setActiveRunId(data.runId);
    setActiveAnalysisId(data.analysisId || null);
    setRelations(data.relations);
    setClausesDoc1(data.clausesDoc1);
    setClausesDoc2(data.clausesDoc2);
    setCurrentScreen('compare');

    // Refresh history
    refreshHistory();
  };

  const handleProcessingError = (
    errorMsg: string,
    runId?: string | null,
    details?: { failedStep?: number; progress?: number; statusMessage?: string }
  ) => {
    setLastErrorMessage(errorMsg);
    if (runId) setActiveRunId(runId);
    setErrorDetails({
      failedStep: details?.failedStep || 3,
      progress: typeof details?.progress === 'number' ? details.progress : 68,
      statusMessage: details?.statusMessage,
    });
    setCurrentScreen('error');
  };

  const handleRetryAnalysis = () => {
    setIsRetry(true);
    setCurrentScreen('processing');
  };

  const handleBackToUpload = () => {
    setIsRetry(false);
    setActiveRunId(null);
    setCurrentScreen('upload');
  };

  const handleLogout = () => {
    LegalApiService.removeAuthToken();
    setIsSidebarOpen(false);
    setIsRetry(false);
    setActiveRunId(null);
    setActiveAnalysisId(null);
    setCurrentScreen('login');
  };

  const handleNewAnalysis = () => {
    setIsRetry(false);
    setActiveRunId(null);
    setActiveAnalysisId(null);
    setDoc1(null);
    setDoc2(null);
    try {
      sessionStorage.removeItem('legal_agent_pending_doc_1');
      sessionStorage.removeItem('legal_agent_pending_doc_2');
    } catch (_) {}
    setCurrentScreen('upload');
  };

  const handleSelectHistoryItem = async (item: HistoryItem) => {
    if (item.analysisId) {
      try {
        // Send analyze_id to /analyze/history/{analyze_id}
        const detail = await LegalApiService.fetchHistoryDetail(item.analysisId);

        const docAId =
          detail.document_a_id ??
          detail.doc_a?.doc_id ??
          item.docAId;

        const docBId =
          detail.document_b_id ??
          detail.doc_b?.doc_id ??
          item.docBId;

        // Fetch structures from detail if provided, or from /api/v1/document/{id}/structure
        let structA: any[] = detail.doc_a?.structure || [];
        let structB: any[] = detail.doc_b?.structure || [];

        if ((!structA.length || !structB.length) && docAId && docBId) {
          const [fetchedA, fetchedB] = await Promise.allSettled([
            !structA.length ? LegalApiService.getDocumentStructure(docAId) : Promise.resolve(structA),
            !structB.length ? LegalApiService.getDocumentStructure(docBId) : Promise.resolve(structB),
          ]);
          if (fetchedA.status === 'fulfilled' && fetchedA.value) structA = fetchedA.value;
          if (fetchedB.status === 'fulfilled' && fetchedB.value) structB = fetchedB.value;
        }

        const titleA = detail.doc_a?.title || item.doc1Name || (docAId ? `سند ${docAId}` : 'سند اول');
        const titleB = detail.doc_b?.title || item.doc2Name || (docBId ? `سند ${docBId}` : 'سند دوم');

        const c1 = transformStructureToClauses(structA);
        const c2 = transformStructureToClauses(structB);
        const relationsData = detail.relations || [];
        const compiled = LegalApiService.compileClausesWithRelations(c1, c2, relationsData);

        const displayDate =
          item.formattedDate ||
          (detail.created_at ? formatPersianDate(detail.created_at) : '') ||
          formatPersianTimeAgo(detail.created_at || item.timeAgo);

        setDoc1({
          id: `doc_${docAId || '1'}`,
          docId: docAId,
          title: titleA,
          fileName: titleA,
          tag: 'سند اول',
          date: displayDate,
          status: 'ready',
        });

        setDoc2({
          id: `doc_${docBId || '2'}`,
          docId: docBId,
          title: titleB,
          fileName: titleB,
          tag: 'سند دوم',
          date: displayDate,
          status: 'ready',
        });

        setClausesDoc1(compiled.clausesDoc1);
        setClausesDoc2(compiled.clausesDoc2);
        setRelations(compiled.relations);
        setActiveAnalysisId(detail.analysis_id || item.analysisId);
        setCurrentScreen('compare');
        setIsSidebarOpen(false);
        return;
      } catch (err) {
        console.warn('Error loading history item detail:', err);
      }
    }
    setCurrentScreen('compare');
    setIsSidebarOpen(false);
  };

  return (
    <div className="min-h-screen w-full bg-[#f7f3ec] text-[#1c1c18] font-sans antialiased relative">
      {/* Sidebar for navigation across the app */}
      {currentScreen !== 'login' && (
        <Sidebar
          isOpen={isSidebarOpen}
          onOpen={() => setIsSidebarOpen(true)}
          onClose={() => setIsSidebarOpen(false)}
          currentUser={currentUser}
          history={history}
          currentScreen={currentScreen}
          onNavigate={(screen) => {
            if (screen === 'upload') {
              handleNewAnalysis();
            } else {
              setCurrentScreen(screen);
            }
          }}
          onSelectHistoryItem={handleSelectHistoryItem}
          onLogout={handleLogout}
          isLoadingHistory={isLoadingHistory}
          onRefreshHistory={refreshHistory}
        />
      )}

      {/* Screen Views with smooth transition */}
      <AnimatePresence mode="wait">
        {currentScreen === 'login' && (
          <motion.div
            key="screen-login"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <AuthScreen onSuccess={handleAuthSuccess} />
          </motion.div>
        )}

        {currentScreen === 'upload' && (
          <motion.div
            key="screen-upload"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <UploadScreen
              userName={currentUser.name}
              doc1={doc1}
              doc2={doc2}
              onStartAnalysis={handleStartAnalysis}
              onOpenSidebar={() => setIsSidebarOpen(true)}
            />
          </motion.div>
        )}

        {currentScreen === 'processing' && doc1 && doc2 && (
          <motion.div
            key={`screen-processing-${isRetry ? 'retry' : 'initial'}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <ProcessingScreen
              doc1={doc1}
              doc2={doc2}
              isRetry={isRetry}
              runId={activeRunId}
              initialStep={errorDetails.failedStep}
              initialProgress={errorDetails.progress}
              onComplete={handleProcessingComplete}
              onError={handleProcessingError}
              onOpenSidebar={() => setIsSidebarOpen(true)}
            />
          </motion.div>
        )}

        {currentScreen === 'error' && (
          <motion.div
            key="screen-error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <ErrorScreen
              doc1={doc1}
              doc2={doc2}
              errorMessage={lastErrorMessage}
              runId={activeRunId}
              failedStep={errorDetails.failedStep}
              progress={errorDetails.progress}
              statusMessage={errorDetails.statusMessage}
              onRetry={handleRetryAnalysis}
              onBackToUpload={handleBackToUpload}
              onOpenSidebar={() => setIsSidebarOpen(true)}
            />
          </motion.div>
        )}

        {currentScreen === 'compare' && (
          <motion.div
            key="screen-compare"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <CompareScreen
              doc1={doc1}
              doc2={doc2}
              clausesDoc1={clausesDoc1}
              clausesDoc2={clausesDoc2}
              relations={relations}
              analysisId={activeAnalysisId}
              onOpenSidebar={() => setIsSidebarOpen(true)}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

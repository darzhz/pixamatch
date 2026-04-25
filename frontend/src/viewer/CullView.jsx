import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Heart, X, RotateCcw, Maximize2, CheckCircle, Info, Loader2, List, Trash2, ChevronDown } from 'lucide-react';

export default function CullView() {
  const { basket_id, token } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [decisions, setDecisions] = useState([]);
  const [history, setHistory] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [showFinished, setShowFinished] = useState(false);
  const [lightboxImage, setLightboxImage] = useState(null);
  const [showFavorites, setShowFavorites] = useState(false);

  // Swipe State
  const [drag, setDrag] = useState({ x: 0, y: 0, active: false });
  const [exitDirection, setExitDirection] = useState(null);
  const cardRef = useRef(null);
  const startPos = useRef({ x: 0, y: 0 });

  const fetchSession = useCallback(async () => {
    try {
      const res = await axios.get(`/api/baskets/${basket_id}/cull/${token}`);
      setSession(res.data);
      if (res.data.status === 'submitted') {
        setShowFinished(true);
      }
    } catch (e) {
      console.error("Error fetching cull session", e);
      alert("Invalid or expired session.");
    } finally {
      setLoading(false);
    }
  }, [basket_id, token]);

  useEffect(() => {
    fetchSession();
  }, [fetchSession]);

  const handleDecision = useCallback((action) => {
    if (currentIndex >= session.queue.length || exitDirection) return;

    const directionMap = { 'keep': 'right', 'discard': 'left', 'unsure': 'up' };
    setExitDirection(directionMap[action]);

    setTimeout(() => {
      const currentImage = session.queue[currentIndex];
      const newDecision = { image_path: currentImage.key, action };
      
      setDecisions(prev => [...prev, newDecision]);
      setHistory(prev => [...prev, { index: currentIndex, decision: newDecision }]);
      
      // Update local session state for Kept photos
      if (action === 'keep') {
        setSession(prev => ({
          ...prev,
          kept: [...prev.kept, currentImage.key]
        }));
      }

      setCurrentIndex(prev => prev + 1);
      setExitDirection(null);
      setDrag({ x: 0, y: 0, active: false });

      if (decisions.length > 0 && decisions.length % 5 === 0) {
        syncDecisions([...decisions, newDecision]);
      }
    }, 300);
  }, [currentIndex, session, decisions, exitDirection]);

  const syncDecisions = async (batch) => {
    try {
      await axios.patch(`/api/baskets/${basket_id}/cull/${token}/decisions`, {
        decisions: batch
      });
      setDecisions([]);
    } catch (e) {
      console.error("Error syncing decisions", e);
    }
  };

  const undo = () => {
    if (history.length === 0 || exitDirection) return;
    const last = history[history.length - 1];
    
    // Remove from kept if it was a 'keep' decision
    if (last.decision.action === 'keep') {
      setSession(prev => ({
        ...prev,
        kept: prev.kept.filter(k => k !== last.decision.image_path)
      }));
    }

    setHistory(prev => prev.slice(0, -1));
    setCurrentIndex(last.index);
  };

  const submit = async () => {
    if (session.kept.length === 0 && !confirm("You haven't selected any photos. Submit anyway?")) return;
    
    setSubmitting(true);
    try {
      if (decisions.length > 0) {
        await syncDecisions(decisions);
      }
      
      const name = prompt("Name this selection (optional):", `Selection by Client`);
      await axios.post(`/api/baskets/${basket_id}/submit-cull`, {
        token,
        name: name || undefined,
        include_unsure: false
      });
      setShowFinished(true);
    } catch (e) {
      console.error("Submit error", e);
      alert("Error submitting. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const onTouchStart = (e) => {
    if (exitDirection || showFavorites) return;
    const touch = e.touches[0];
    startPos.current = { x: touch.clientX, y: touch.clientY };
    setDrag(prev => ({ ...prev, active: true }));
  };

  const onTouchMove = (e) => {
    if (!drag.active || exitDirection) return;
    const touch = e.touches[0];
    const dx = touch.clientX - startPos.current.x;
    const dy = touch.clientY - startPos.current.y;
    setDrag({ x: dx, y: dy, active: true });
  };

  const onTouchEnd = () => {
    if (!drag.active || exitDirection) return;
    const threshold = 100;
    
    if (drag.x > threshold) {
      handleDecision('keep');
    } else if (drag.x < -threshold) {
      handleDecision('discard');
    } else if (drag.y < -threshold) {
      handleDecision('unsure');
    } else {
      setDrag({ x: 0, y: 0, active: false });
    }
  };

  if (loading) return (
    <div className="h-screen flex items-center justify-center bg-gray-900 text-white">
      <Loader2 className="animate-spin" size={48} />
    </div>
  );

  if (showFinished) return (
    <div className="h-screen flex flex-col items-center justify-center bg-gray-900 text-white p-6 text-center animate-in fade-in duration-700">
      <div className="bg-green-500 w-20 h-20 rounded-full flex items-center justify-center mb-6 shadow-[0_0_40px_rgba(34,197,94,0.4)]">
        <CheckCircle size={48} />
      </div>
      <h2 className="text-3xl font-black mb-4 tracking-tighter">SUBMITTED!</h2>
      <p className="text-gray-400 mb-8 max-w-sm">
        The photographer has been notified. You can safely close this window.
      </p>
      <button 
        onClick={() => navigate('/')}
        className="px-10 py-4 bg-white text-black rounded-2xl font-black shadow-xl"
      >
        Done
      </button>
    </div>
  );

  const queue = session.queue;
  const currentImage = queue[currentIndex];
  const nextImage = queue[currentIndex + 1];

  const getCardStyle = () => {
    if (exitDirection) {
      const transform = {
        left: 'translate3d(-150%, 0, 0) rotate(-20deg)',
        right: 'translate3d(150%, 0, 0) rotate(20deg)',
        up: 'translate3d(0, -150%, 0)'
      }[exitDirection];
      return { transform, transition: 'all 0.3s ease-out', opacity: 0 };
    }
    if (drag.active) {
      return { 
        transform: `translate3d(${drag.x}px, ${drag.y}px, 0) rotate(${drag.x * 0.1}deg)`,
        transition: 'none'
      };
    }
    return { 
      transform: 'translate3d(0,0,0)', 
      transition: 'all 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275)' 
    };
  };

  return (
    <div className="h-screen bg-black text-white overflow-hidden flex flex-col relative font-sans select-none touch-none">
      {/* Header */}
      <header className="px-6 py-4 flex justify-between items-center z-10 shrink-0 border-b border-white/5 bg-black/50 backdrop-blur-md">
        <div className="flex items-center gap-4">
          <button 
            onClick={() => setShowFavorites(true)}
            className="relative p-2 bg-white/10 rounded-xl"
          >
            <Heart size={20} fill={session.kept.length > 0 ? "white" : "none"} />
            {session.kept.length > 0 && (
              <span className="absolute -top-1 -right-1 bg-purple-600 text-[10px] font-black w-4 h-4 rounded-full flex items-center justify-center">
                {session.kept.length}
              </span>
            )}
          </button>
          <div className="flex flex-col">
            <h1 className="text-sm font-black tracking-tighter opacity-50 uppercase">Culling Session</h1>
            <p className="text-lg font-black tracking-tight leading-none">
              {currentIndex} <span className="text-gray-600">/ {queue.length}</span>
            </p>
          </div>
        </div>
        
        <div className="flex gap-2">
          <button 
            onClick={undo}
            disabled={history.length === 0 || exitDirection}
            className="p-2 bg-white/5 rounded-xl disabled:opacity-20"
          >
            <RotateCcw size={20} />
          </button>
          <button 
            onClick={submit}
            disabled={submitting}
            className="px-4 py-2 bg-white text-black rounded-xl font-black text-xs uppercase tracking-widest shadow-lg hover:scale-105 transition-transform"
          >
            {submitting ? <Loader2 className="animate-spin" size={16} /> : "Finish"}
          </button>
        </div>
      </header>

      {/* Card Stack */}
      <div className="flex-1 relative flex items-center justify-center p-4">
        {currentIndex < queue.length ? (
          <div className="relative w-full max-w-md aspect-[3/4]">
            {nextImage && (
              <div className="absolute inset-0 rounded-3xl bg-gray-800 scale-95 translate-y-4 opacity-40 shadow-2xl overflow-hidden">
                <img src={nextImage.url} className="w-full h-full object-cover grayscale opacity-50" alt="" />
              </div>
            )}

            <div 
              ref={cardRef}
              onTouchStart={onTouchStart}
              onTouchMove={onTouchMove}
              onTouchEnd={onTouchEnd}
              style={getCardStyle()}
              className="absolute inset-0 rounded-[2.5rem] bg-gray-900 shadow-[0_20px_50px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col cursor-grab active:cursor-grabbing border border-white/10"
            >
               <img 
                 src={currentImage.url} 
                 className="w-full h-full object-cover pointer-events-none" 
                 alt="Review" 
               />
               
               <button 
                 onClick={(e) => { e.stopPropagation(); setLightboxImage(currentImage.url); }}
                 className="absolute top-4 right-4 p-3 bg-black/40 rounded-full backdrop-blur-xl border border-white/10"
               >
                 <Maximize2 size={24} />
               </button>

               {/* Swipe Hints */}
               {drag.active && (
                 <div className="absolute inset-0 flex items-center justify-center pointer-events-none p-10">
                    {drag.x > 80 && (
                      <div className="bg-green-500 text-white px-8 py-4 rounded-3xl font-black text-4xl rotate-[-12deg] border-4 border-white shadow-2xl animate-in zoom-in duration-100">
                        KEEP
                      </div>
                    )}
                    {drag.x < -80 && (
                      <div className="bg-red-500 text-white px-8 py-4 rounded-3xl font-black text-4xl rotate-[12deg] border-4 border-white shadow-2xl animate-in zoom-in duration-100">
                        SKIP
                      </div>
                    )}
                    {drag.y < -80 && Math.abs(drag.x) < 50 && (
                      <div className="bg-gray-500 text-white px-8 py-4 rounded-3xl font-black text-4xl border-4 border-white shadow-2xl animate-in zoom-in duration-100">
                        MAYBE
                      </div>
                    )}
                 </div>
               )}
            </div>
          </div>
        ) : (
          <div className="text-center p-8 max-w-sm animate-in fade-in slide-in-from-bottom-10 duration-500">
             <div className="bg-purple-600/20 w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-8 border border-purple-500/50">
                <CheckCircle size={48} className="text-purple-500" />
             </div>
             <h3 className="text-3xl font-black mb-4 tracking-tighter leading-tight text-white">READY TO SUBMIT?</h3>
             <p className="text-gray-500 mb-10 text-lg leading-relaxed">
               You've reviewed all photos. You can review your {session.kept.length} favorites before finishing.
             </p>
             <div className="flex flex-col gap-4">
               <button 
                onClick={() => setShowFavorites(true)}
                className="w-full py-5 bg-white/5 border border-white/10 rounded-2xl font-black text-lg transition-all active:scale-95"
               >
                 Review Choices
               </button>
               <button 
                 onClick={submit}
                 disabled={submitting}
                 className="w-full py-5 bg-purple-600 text-white rounded-2xl font-black text-lg shadow-[0_10px_30px_rgba(147,51,234,0.3)] transition-all active:scale-95 flex items-center justify-center gap-3"
               >
                 {submitting ? <Loader2 className="animate-spin" /> : "Finish & Send"}
               </button>
             </div>
          </div>
        )}
      </div>

      {/* Controls */}
      {currentIndex < queue.length && (
        <div className="px-10 pb-12 pt-6 flex justify-between items-center z-10 shrink-0 max-w-md mx-auto w-full">
          <button 
            onClick={() => handleDecision('discard')}
            disabled={exitDirection}
            className="w-20 h-20 bg-red-500/10 border-2 border-red-500/50 text-red-500 rounded-full flex items-center justify-center shadow-lg hover:bg-red-500 hover:text-white transition-all active:scale-90"
          >
            <X size={36} />
          </button>
          
          <button 
            onClick={() => handleDecision('unsure')}
            disabled={exitDirection}
            className="w-14 h-14 bg-white/5 border border-white/10 text-gray-400 rounded-full flex items-center justify-center shadow-lg transition-all active:scale-90"
            title="Maybe"
          >
            <Info size={28} />
          </button>

          <button 
            onClick={() => handleDecision('keep')}
            disabled={exitDirection}
            className="w-20 h-20 bg-green-500 border-2 border-green-400 text-white rounded-full flex items-center justify-center shadow-[0_15px_35px_rgba(34,197,94,0.3)] hover:scale-110 transition-all active:scale-90"
          >
            <Heart size={36} fill="white" />
          </button>
        </div>
      )}

      {/* Favorites Modal (The "Selected Photos" view) */}
      {showFavorites && (
        <div className="fixed inset-0 z-[60] bg-black/95 backdrop-blur-2xl flex flex-col animate-in fade-in slide-in-from-bottom-10 duration-300">
          <header className="px-6 py-6 flex justify-between items-center border-b border-white/10">
             <div className="flex items-center gap-3">
                <Heart fill="white" size={24} className="text-purple-500" />
                <h2 className="text-2xl font-black tracking-tighter uppercase">My Favorites</h2>
                <span className="text-gray-500 font-mono text-sm">({session.kept.length})</span>
             </div>
             <button 
               onClick={() => setShowFavorites(false)}
               className="p-3 bg-white/10 rounded-full"
             >
               <ChevronDown size={28} />
             </button>
          </header>
          
          <div className="flex-1 overflow-y-auto p-4 md:p-8">
            {session.kept.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-500">
                <Heart size={64} className="mb-4 opacity-10" />
                <p className="text-xl font-bold">No photos selected yet.</p>
                <p className="text-sm mt-2">Swipe right on photos to add them here.</p>
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                {session.kept.map((imagePath) => (
                  <div key={imagePath} className="relative aspect-[3/4] rounded-2xl overflow-hidden group shadow-xl border border-white/5">
                    <img 
                      src={`/api/pixamatch/${imagePath}`} // Use Minio proxy URL (needs verification of endpoint)
                      alt="Selected"
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-4">
                       <button 
                         onClick={() => {
                           setSession(prev => ({ ...prev, kept: prev.kept.filter(k => k !== imagePath) }));
                         }}
                         className="flex items-center gap-2 bg-red-600/90 text-white px-3 py-2 rounded-xl text-xs font-bold"
                       >
                         <Trash2 size={14} /> Remove
                       </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          
          <footer className="p-6 border-t border-white/10 bg-black">
             <button 
               onClick={submit}
               className="w-full py-5 bg-white text-black rounded-2xl font-black text-xl shadow-2xl transition-all active:scale-95"
             >
               Finalize & Submit Choices
             </button>
          </footer>
        </div>
      )}

      {/* Fullscreen Lightbox */}
      {lightboxImage && (
        <div 
          className="fixed inset-0 z-[100] bg-black flex items-center justify-center p-2 animate-in fade-in duration-200"
          onClick={() => setLightboxImage(null)}
        >
          <img src={lightboxImage} className="max-w-full max-h-full object-contain rounded-lg" alt="Fullscreen" />
          <button className="absolute top-6 right-6 p-4 bg-white/20 rounded-full backdrop-blur-xl border border-white/10">
            <X size={28} />
          </button>
        </div>
      )}

      {/* Keyboard support */}
      <KeyboardHandler 
        onLeft={() => handleDecision('discard')} 
        onRight={() => handleDecision('keep')} 
        onUp={() => handleDecision('unsure')}
        onSpace={() => setLightboxImage(currentImage?.url)}
        onZ={undo}
      />
    </div>
  );
}

function KeyboardHandler({ onLeft, onRight, onUp, onSpace, onZ }) {
  useEffect(() => {
    const handleDown = (e) => {
      if (e.key === 'ArrowLeft') onLeft();
      if (e.key === 'ArrowRight') onRight();
      if (e.key === 'ArrowUp') onUp();
      if (e.key === ' ') { e.preventDefault(); onSpace(); }
      if (e.key.toLowerCase() === 'z') onZ();
    };
    window.addEventListener('keydown', handleDown);
    return () => window.removeEventListener('keydown', handleDown);
  }, [onLeft, onRight, onUp, onSpace, onZ]);
  return null;
}

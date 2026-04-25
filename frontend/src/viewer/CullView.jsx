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
  const [_decisions, setDecisions] = useState([]);
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
      setCurrentIndex(res.data.current_index || 0);
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

  const syncDecisions = async (batch, newIndex) => {
    try {
      await axios.patch(`/api/baskets/${basket_id}/cull/${token}/decisions`, {
        decisions: batch,
        current_index: newIndex
      });
      setDecisions([]);
    } catch (e) {
      console.error("Error syncing decisions", e);
    }
  };

  const handleDecision = useCallback((action) => {
    if (!session || currentIndex >= session.queue.length || exitDirection) return;

    const directionMap = { 'keep': 'right', 'discard': 'left', 'unsure': 'up' };
    setExitDirection(directionMap[action]);

    const currentImage = session.queue[currentIndex];
    const newDecision = { image_path: currentImage.key, action };
    const nextIndex = currentIndex + 1;

    setTimeout(() => {
      setDecisions(prev => [...prev, newDecision]);
      setHistory(prev => [...prev, { index: currentIndex, decision: newDecision }]);
      
      if (action === 'keep') {
        setSession(prev => ({
          ...prev,
          kept: [...prev.kept, currentImage.key]
        }));
      }

      setCurrentIndex(nextIndex);
      setExitDirection(null);
      setDrag({ x: 0, y: 0, active: false });

      // Sync immediately for better persistence
      syncDecisions([newDecision], nextIndex);
    }, 400);
  }, [currentIndex, session, exitDirection]);

  const undo = () => {
    if (history.length === 0 || exitDirection) return;
    const last = history[history.length - 1];
    const prevIndex = last.index;
    
    if (last.decision.action === 'keep') {
      setSession(prev => ({
        ...prev,
        kept: prev.kept.filter(k => k !== last.decision.image_path)
      }));
    }

    setHistory(prev => prev.slice(0, -1));
    setCurrentIndex(prevIndex);
    syncDecisions([], prevIndex); // Sync the index back
  };

  const submit = async () => {
    if (session.kept.length === 0 && !confirm("You haven't selected any photos. Submit anyway?")) return;
    
    setSubmitting(true);
    try {
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

  // Improved Touch Handlers for Tinder-like feel
  const onTouchStart = (e) => {
    if (exitDirection || showFavorites) return;
    const touch = e.touches[0];
    startPos.current = { x: touch.clientX, y: touch.clientY };
    setDrag({ x: 0, y: 0, active: true });
  };

  const onTouchMove = (e) => {
    if (!drag.active || exitDirection) return;
    const touch = e.touches[0];
    const dx = touch.clientX - startPos.current.x;
    const dy = touch.clientY - startPos.current.y;
    
    // Tinder-like rotation based on x offset
    setDrag({ x: dx, y: dy, active: true });
  };

  const onTouchEnd = () => {
    if (!drag.active || exitDirection) return;
    const threshold = window.innerWidth * 0.3; // Responsive threshold
    
    if (Math.abs(drag.x) > threshold) {
      handleDecision(drag.x > 0 ? 'keep' : 'discard');
    } else if (drag.y < -threshold && Math.abs(drag.x) < threshold) {
      handleDecision('unsure');
    } else {
      // Spring back animation
      setDrag({ x: 0, y: 0, active: false });
    }
  };

  // Helper to find URL for a key from the queue
  const getUrlForKey = (key) => {
    return session?.queue.find(item => item.key === key)?.url;
  };

  if (loading) return (
    <div className="h-screen flex items-center justify-center bg-gray-900 text-white font-sans">
      <div className="text-center">
        <Loader2 className="animate-spin mb-4 mx-auto" size={48} />
        <p className="text-gray-400 font-bold uppercase tracking-widest text-xs">Loading Session...</p>
      </div>
    </div>
  );

  if (showFinished) return (
    <div className="h-screen flex flex-col items-center justify-center bg-gray-900 text-white p-6 text-center animate-in fade-in duration-700 font-sans">
      <div className="bg-green-500 w-24 h-24 rounded-full flex items-center justify-center mb-8 shadow-[0_0_50px_rgba(34,197,94,0.5)]">
        <CheckCircle size={56} />
      </div>
      <h2 className="text-4xl font-black mb-4 tracking-tighter italic">SUBMITTED!</h2>
      <p className="text-gray-400 mb-10 max-w-sm text-lg">
        Your selections have been sent to the photographer.
      </p>
      <button 
        onClick={() => navigate(`/find/${basket_id}`)}
        className="px-12 py-5 bg-white text-black rounded-[2rem] font-black shadow-2xl hover:scale-105 active:scale-95 transition-all text-xl"
      >
        Return to search 
      </button>
    </div>
  );

  const queue = session.queue;
  const currentImage = queue[currentIndex];
  const nextImage = queue[currentIndex + 1];

  const getCardStyle = (isTop) => {
    if (!isTop) {
      const isRevealing = exitDirection !== null;
      return {
        transform: isRevealing ? 'translate3d(0, 0, 0) scale(1)' : 'translate3d(0, 30px, 0) scale(0.9)',
        opacity: isRevealing ? 1 : 0.4,
        zIndex: 30,
        filter: isRevealing ? 'grayscale(0) blur(0px)' : 'grayscale(0.5) blur(2px)',
        transition: 'all 0.6s cubic-bezier(0.23, 1, 0.32, 1)'
      };
    }

    if (exitDirection) {
      const transform = {
        left: 'translate3d(-200%, 0, 0) rotate(-30deg)',
        right: 'translate3d(200%, 0, 0) rotate(30deg)',
        up: 'translate3d(0, -200%, 0)'
      }[exitDirection];
      return { transform, transition: 'all 0.4s cubic-bezier(0.3, 0, 0.2, 1)', opacity: 0, zIndex: 50 };
    }

    if (drag.active) {
      // Rotation increases as you drag away from center
      const rotation = drag.x * 0.05;
      return { 
        transform: `translate3d(${drag.x}px, ${drag.y}px, 0) rotate(${rotation}deg)`,
        transition: 'none',
        zIndex: 50
      };
    }

    return { 
      transform: 'translate3d(0,0,0) rotate(0deg) scale(1)', 
      transition: 'all 0.6s cubic-bezier(0.23, 1, 0.32, 1)',
      zIndex: 40,
      opacity: 1
    };
  };

  return (
    <div className="h-screen bg-[#0a0a0a] text-white overflow-hidden flex flex-col relative font-sans select-none">
      {/* Header */}
      <header className="px-6 py-5 flex justify-between items-center z-[100] shrink-0 border-b border-white/5 bg-black/40 backdrop-blur-2xl">
        <div className="flex items-center gap-4">
          <button 
            onClick={() => setShowFavorites(true)}
            className="relative p-3 bg-white/10 rounded-2xl hover:bg-white/20 transition-colors"
          >
            <Heart size={24} fill={session.kept.length > 0 ? "white" : "none"} className={session.kept.length > 0 ? "text-red-500" : ""} />
            {session.kept.length > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-[10px] font-black w-5 h-5 rounded-full flex items-center justify-center border-2 border-[#0a0a0a]">
                {session.kept.length}
              </span>
            )}
          </button>
          <div className="flex flex-col">
            <h1 className="text-[10px] font-black tracking-[0.2em] opacity-40 uppercase">Session Progress</h1>
            <p className="text-xl font-black tracking-tighter leading-none flex items-baseline gap-1">
              {currentIndex + 1} <span className="text-white/20 text-sm font-bold">/ {queue.length}</span>
            </p>
          </div>
        </div>
        
        <div className="flex gap-3">
          <button 
            onClick={undo}
            disabled={history.length === 0 || exitDirection}
            className="p-3 bg-white/5 rounded-2xl disabled:opacity-20 hover:bg-white/10 transition-colors"
            title="Undo (Z)"
          >
            <RotateCcw size={22} />
          </button>
          <button 
            onClick={submit}
            disabled={submitting}
            className="px-6 py-3 bg-white text-black rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl hover:scale-105 active:scale-95 transition-all"
          >
            {submitting ? <Loader2 className="animate-spin" size={16} /> : "Finish"}
          </button>
        </div>
      </header>

      {/* Main Card View */}
      <div className="flex-1 relative flex items-center justify-center p-6 overflow-hidden">
        {currentIndex < queue.length ? (
          <div className="relative w-full max-w-[400px] h-full max-h-[600px] perspective-[1000px]">
            {[nextImage, currentImage].filter(Boolean).map((image, i, arr) => {
              const isTop = i === arr.length - 1;
              return (
                <div 
                  key={image.key}
                  ref={isTop ? cardRef : null}
                  onMouseDown={(e) => {
                    if (!isTop || exitDirection || showFavorites) return;
                    startPos.current = { x: e.clientX, y: e.clientY };
                    setDrag({ x: 0, y: 0, active: true });
                    const handleMove = (ev) => {
                      setDrag({ x: ev.clientX - startPos.current.x, y: ev.clientY - startPos.current.y, active: true });
                    };
                    const handleUp = (ev) => {
                      window.removeEventListener('mousemove', handleMove);
                      window.removeEventListener('mouseup', handleUp);
                      const dx = ev.clientX - startPos.current.x;
                      const dy = ev.clientY - startPos.current.y;
                      const threshold = 120;
                      if (Math.abs(dx) > threshold) {
                        handleDecision(dx > 0 ? 'keep' : 'discard');
                      } else if (dy < -threshold && Math.abs(dx) < threshold) {
                        handleDecision('unsure');
                      } else {
                        setDrag({ x: 0, y: 0, active: false });
                      }
                    };
                    window.addEventListener('mousemove', handleMove);
                    window.addEventListener('mouseup', handleUp);
                  }}
                  onTouchStart={isTop ? onTouchStart : undefined}
                  onTouchMove={isTop ? onTouchMove : undefined}
                  onTouchEnd={isTop ? onTouchEnd : undefined}
                  style={getCardStyle(isTop)}
                  className={`absolute inset-0 rounded-[3rem] overflow-hidden flex flex-col border border-white/10 shadow-2xl transition-all ${isTop ? 'bg-zinc-800 cursor-grab active:cursor-grabbing touch-none z-40' : 'bg-zinc-900 z-0'}`}
                >
                  <img 
                    src={image.url} 
                    className={`w-full h-full object-cover pointer-events-none transition-all duration-700 ${!isTop ? 'grayscale opacity-20 blur-sm' : ''}`} 
                    alt="Review" 
                  />
                  
                  {isTop && (
                    <>
                      {/* Controls on Card */}
                      <div className="absolute top-6 left-6 right-6 flex justify-between items-start pointer-events-none">
                          <div className="p-3 bg-black/40 rounded-full backdrop-blur-xl border border-white/10 opacity-60">
                            <Info size={18} />
                          </div>
                          <button 
                            onClick={(e) => { e.stopPropagation(); setLightboxImage(image.url); }}
                            className="p-4 bg-black/40 rounded-full backdrop-blur-xl border border-white/10 pointer-events-auto hover:bg-black/60 transition-colors"
                          >
                            <Maximize2 size={24} />
                          </button>
                      </div>

                      {/* Swipe Labels (Tinder Style) */}
                      {drag.active && (
                        <div className="absolute inset-0 flex items-center justify-center pointer-events-none p-10 z-[60]">
                            {drag.x > 50 && (
                              <div className="absolute top-12 left-8 border-4 border-green-500 text-green-500 px-6 py-2 rounded-xl font-black text-4xl rotate-[-15deg] uppercase shadow-2xl scale-110">
                                Keep
                              </div>
                            )}
                            {drag.x < -50 && (
                              <div className="absolute top-12 right-8 border-4 border-red-500 text-red-500 px-6 py-2 rounded-xl font-black text-4xl rotate-[15deg] uppercase shadow-2xl scale-110">
                                Skip
                              </div>
                            )}
                            {drag.y < -50 && Math.abs(drag.x) < 50 && (
                              <div className="absolute bottom-20 border-4 border-zinc-400 text-zinc-400 px-6 py-2 rounded-xl font-black text-4xl uppercase shadow-2xl scale-110">
                                Maybe
                              </div>
                            )}
                        </div>
                      )}

                      {/* Grad Info */}
                      <div className="absolute bottom-0 inset-x-0 h-40 bg-gradient-to-t from-black via-black/40 to-transparent pointer-events-none flex flex-col justify-end p-8">
                          <span className="text-[10px] font-bold text-white/40 uppercase tracking-widest mb-1">Image Key</span>
                          <p className="text-sm text-white font-mono truncate opacity-60">{image.key}</p>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center p-10 max-w-sm animate-in fade-in slide-in-from-bottom-12 duration-700 bg-zinc-900/50 rounded-[3rem] border border-white/5 backdrop-blur-xl">
             <div className="bg-purple-600/20 w-28 h-28 rounded-full flex items-center justify-center mx-auto mb-10 border border-purple-500/30">
                <CheckCircle size={56} className="text-purple-500" />
             </div>
             <h3 className="text-4xl font-black mb-4 tracking-tighter italic uppercase text-white">All Caught Up!</h3>
             <p className="text-gray-400 mb-12 text-lg leading-relaxed font-medium">
               You've reviewed every photo in this session.
             </p>
             <div className="flex flex-col gap-4">
               <button 
                onClick={() => setShowFavorites(true)}
                className="w-full py-6 bg-white/5 border border-white/10 rounded-[1.5rem] font-black text-lg transition-all hover:bg-white/10 active:scale-95"
               >
                 Review {session.kept.length} Choices
               </button>
               <button 
                 onClick={submit}
                 disabled={submitting}
                 className="w-full py-6 bg-purple-600 text-white rounded-[1.5rem] font-black text-xl shadow-[0_15px_40px_rgba(147,51,234,0.4)] transition-all hover:scale-[1.02] active:scale-95 flex items-center justify-center gap-3 uppercase tracking-tighter italic"
               >
                 {submitting ? <Loader2 className="animate-spin" /> : "Submit To Studio"}
               </button>
             </div>
          </div>
        )}
      </div>

      {/* Bottom Fixed Controls */}
      {currentIndex < queue.length && (
        <div className="px-10 pb-16 pt-8 flex justify-center items-center z-[100] gap-8 shrink-0">
          <button 
            onClick={() => handleDecision('discard')}
            disabled={exitDirection}
            className="w-20 h-20 bg-zinc-900 border border-white/10 text-red-500 rounded-full flex items-center justify-center shadow-2xl hover:scale-110 active:scale-90 transition-all group"
          >
            <X size={40} className="group-hover:rotate-90 transition-transform duration-300" />
          </button>
          
          <button 
            onClick={() => handleDecision('unsure')}
            disabled={exitDirection}
            className="w-16 h-16 bg-zinc-900 border border-white/10 text-zinc-400 rounded-full flex items-center justify-center shadow-xl hover:scale-110 active:scale-90 transition-all"
          >
            <Info size={30} />
          </button>

          <button 
            onClick={() => handleDecision('keep')}
            disabled={exitDirection}
            className="w-20 h-20 bg-zinc-900 border border-white/10 text-green-500 rounded-full flex items-center justify-center shadow-2xl hover:scale-110 active:scale-90 transition-all group"
          >
            <Heart size={40} className="group-hover:scale-125 transition-transform duration-300" />
          </button>
        </div>
      )}

      {/* Favorites Modal */}
      {showFavorites && (
        <div className="fixed inset-0 z-[200] bg-black flex flex-col animate-in fade-in duration-300 font-sans">
          <header className="px-8 py-8 flex justify-between items-center border-b border-white/10 bg-black/50 backdrop-blur-3xl">
             <div className="flex items-center gap-4">
                <div className="bg-red-500/10 p-3 rounded-2xl">
                  <Heart fill="currentColor" size={28} className="text-red-500" />
                </div>
                <div className="flex flex-col">
                  <h2 className="text-3xl font-black tracking-tighter uppercase italic leading-none">Your Picks</h2>
                  <span className="text-white/40 font-black text-xs tracking-widest mt-1 uppercase">({session.kept.length} Selected)</span>
                </div>
             </div>
             <button 
               onClick={() => setShowFavorites(false)}
               className="p-4 bg-zinc-900 rounded-full hover:bg-zinc-800 transition-colors"
             >
               <ChevronDown size={32} />
             </button>
          </header>
          
          <div className="flex-1 overflow-y-auto p-6 md:p-12 bg-black">
            {session.kept.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-white/20">
                <Heart size={100} className="mb-6 opacity-5" />
                <p className="text-2xl font-black italic uppercase tracking-tight">Empty List</p>
                <p className="text-sm mt-2 font-bold tracking-widest opacity-40 uppercase">Swipe right to select favorites</p>
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-6">
                {session.kept.map((key) => (
                  <div key={key} className="relative aspect-[3/4] rounded-[2rem] overflow-hidden group shadow-2xl border border-white/5">
                    <img 
                      src={getUrlForKey(key)}
                      alt="Selected"
                      className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-110"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center p-6">
                       <button 
                         onClick={() => {
                           setSession(prev => ({ ...prev, kept: prev.kept.filter(k => k !== key) }));
                         }}
                         className="w-full flex items-center justify-center gap-3 bg-red-600 text-white py-4 rounded-2xl text-xs font-black uppercase tracking-widest shadow-xl hover:bg-red-500 transition-colors"
                       >
                         <Trash2 size={16} /> Remove
                       </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          
          <footer className="p-8 border-t border-white/10 bg-zinc-900/50 backdrop-blur-3xl">
             <button 
               onClick={() => { setShowFavorites(false); submit(); }}
               className="w-full py-7 bg-white text-black rounded-[2rem] font-black text-2xl shadow-[0_20px_50px_rgba(255,255,255,0.1)] transition-all hover:scale-[1.01] active:scale-95 uppercase italic tracking-tighter"
             >
               Finalize & Submit
             </button>
          </footer>
        </div>
      )}

      {/* Fullscreen Lightbox */}
      {lightboxImage && (
        <div 
          className="fixed inset-0 z-[300] bg-black flex items-center justify-center p-4 animate-in fade-in duration-300 cursor-zoom-out"
          onClick={() => setLightboxImage(null)}
        >
          <img src={lightboxImage} className="max-w-full max-h-full object-contain rounded-3xl shadow-[0_0_100px_rgba(0,0,0,0.9)]" alt="Fullscreen" />
          <button className="absolute top-8 right-8 p-5 bg-white/10 rounded-full backdrop-blur-2xl border border-white/10 hover:bg-white/20 transition-colors">
            <X size={32} />
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

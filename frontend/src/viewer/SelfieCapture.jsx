import React, { useState, useRef, useEffect, useCallback } from 'react';
import Webcam from 'react-webcam';
import { Camera, RotateCcw, User } from 'lucide-react';

const POSES = [
  { id: 'front', label: 'Face Forward', instruction: 'Look directly at the camera', icon: <User size={48} /> },
  { id: 'left', label: 'Turn Left', instruction: 'Show your left profile', icon: <User className="rotate-[-45deg]" size={48} /> },
  { id: 'right', label: 'Turn Right', instruction: 'Show your right profile', icon: <User className="rotate-[45deg]" size={48} /> }
];

export default function SelfieCapture({ onComplete }) {
  const [step, setStep] = useState(0);
  const [captures, setCaptures] = useState({});
  const [isCapturing, setIsCapturing] = useState(false);
  const [showFlash, setShowFlash] = useState(false);
  const webcamRef = useRef(null);

  const currentPose = POSES[step];

  const videoConstraints = React.useMemo(() => ({ 
    facingMode: "user", 
    aspectRatio: 3/4 
  }), []);

  const capture = useCallback(() => {
    if (!webcamRef.current) return;
    
    const imageSrc = webcamRef.current.getScreenshot();
    if (imageSrc) {
      setCaptures(prev => ({ ...prev, [currentPose.id]: imageSrc }));
    }
    
    setShowFlash(false);
    setIsCapturing(false);
    
    if (step < POSES.length - 1) {
      setStep(s => s + 1);
    }
  }, [webcamRef, step, currentPose]);

  const handleCaptureClick = () => {
    setIsCapturing(true);
    setShowFlash(true);
    setTimeout(capture, 300);
  };

  const reset = () => {
    setStep(0);
    setCaptures({});
    setIsCapturing(false);
    setShowFlash(false);
  };

  useEffect(() => {
    if (Object.keys(captures).length === POSES.length) {
      onComplete(captures);
    }
  }, [captures, onComplete]);

  return (
    <div className="max-w-md mx-auto bg-white rounded-3xl overflow-hidden shadow-2xl border border-gray-100">
      {/* Header */}
      <div className="p-6 text-center border-b border-gray-50">
        <h3 className="text-xl font-bold text-gray-900">{currentPose.label}</h3>
        <p className="text-gray-500 text-sm mt-1">{currentPose.instruction}</p>
      </div>

      {/* Viewport */}
      <div className="relative aspect-[3/4] bg-gray-900 overflow-hidden">
        {/* Webcam */}
        <Webcam
          audio={false}
          ref={webcamRef}
          screenshotFormat="image/webp"
          videoConstraints={videoConstraints}
          className="w-full h-full object-cover grayscale-[0.2]"
        />

        {/* Overlay Guide */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          {/* Animated Face Outline */}
          <div className={`w-64 h-80 border-2 border-dashed rounded-[100px] transition-all duration-500 ${isCapturing ? 'border-purple-500 scale-105' : 'border-white/30 scale-100'}`}>
            <div className="absolute inset-0 bg-purple-500/10 rounded-[100px] animate-pulse" />
          </div>
          
          {/* Pose Icon Hint */}
          <div className="absolute bottom-10 bg-white/10 backdrop-blur-md p-4 rounded-full text-white animate-bounce">
            {currentPose.icon}
          </div>
        </div>

        {/* Flash Effect */}
        {showFlash && (
          <div className="absolute inset-0 bg-white opacity-0 animate-flash pointer-events-none" />
        )}
      </div>

      {/* Footer Controls */}
      <div className="p-8 bg-white">
        {/* Progress Bar */}
        <div className="flex gap-2 mb-8">
          {POSES.map((p, i) => (
            <div 
              key={p.id}
              className={`h-1.5 flex-1 rounded-full transition-colors duration-300 ${i <= step ? 'bg-purple-600' : 'bg-gray-100'}`}
            />
          ))}
        </div>

        <div className="flex items-center justify-between">
          <button 
            onClick={reset}
            className="p-4 text-gray-400 hover:text-gray-600 transition"
          >
            <RotateCcw size={24} />
          </button>
          
          <button 
            onClick={handleCaptureClick}
            disabled={isCapturing}
            className="w-20 h-20 bg-purple-600 rounded-full flex items-center justify-center shadow-lg shadow-purple-200 active:scale-95 disabled:opacity-50 transition-transform border-4 border-white"
          >
            <Camera className="text-white" size={32} />
          </button>

          <div className="w-12" /> {/* Spacer */}
        </div>
      </div>

      <style>{`
        @keyframes flash {
          0% { opacity: 0; }
          50% { opacity: 1; }
          100% { opacity: 0; }
        }
        .animate-flash {
          animation: flash 0.3s ease-out forwards;
        }
      `}</style>
    </div>
  );
}

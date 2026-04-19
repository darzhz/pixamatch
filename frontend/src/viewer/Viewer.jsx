import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { Camera, Upload, Sparkles, Download, Share2, X, AlertCircle } from 'lucide-react';
import SelfieCapture from './SelfieCapture';

const API_BASE = '/api';
const DEBUG = true;

export default function Viewer() {
  const { basket_id } = useParams();
  const [basketInfo, setBasketInfo] = useState(null);
  const [searching, setSearching] = useState(false);
  const [showCapture, setShowCapture] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchInfo = async () => {
      try {
        const res = await axios.get(`${API_BASE}/baskets/${basket_id}/info`);
        setBasketInfo(res.data);
      } catch (e) {
        setError("Basket not found or error loading.");
      }
    };
    fetchInfo();
  }, [basket_id]);

  const onSelfieComplete = async (captures) => {
    setShowCapture(false);
    setSearching(true);
    setResults(null);
    setError(null);

    const formData = new FormData();
    
    // Helper to convert dataUrl to File
    const toFile = async (dataUrl, name) => {
      const blob = await (await fetch(dataUrl)).blob();
      return new File([blob], name, { type: "image/webp" });
    };

    try {
      if (captures.front) formData.append('front', await toFile(captures.front, "front.webp"));
      if (captures.left) formData.append('left', await toFile(captures.left, "left.webp"));
      if (captures.right) formData.append('right', await toFile(captures.right, "right.webp"));

      const startTime = performance.now();
      const res = await axios.post(`${API_BASE}/baskets/${basket_id}/search`, formData);
      const endTime = performance.now();
      console.log(`Search took ${(endTime - startTime).toFixed(2)}ms`);
      
      if (res.data.no_match) {
        setResults([]); // Explicitly set to empty array
        setError(res.data.reason || "No photos found matching your face.");
      } else {
        setResults(res.data.matches);
      }
    } catch (e) {
      setError("Error during search: " + e.message);
    } finally {
      setSearching(false);
    }
  };

  const onFileUpload = (e) => {
    const file = e.target.files[0];
    if (file) performQuickSearch(file);
  };

  const performQuickSearch = async (file) => {
    setSearching(true);
    setResults(null);
    setError(null);

    const formData = new FormData();
    formData.append('front', file);

    try {
      const startTime = performance.now();
      const res = await axios.post(`${API_BASE}/baskets/${basket_id}/search`, formData);
      const endTime = performance.now();
      console.log(`Quick Search took ${(endTime - startTime).toFixed(2)}ms`);

      if (res.data.no_match) {
        setResults([]);
        setError(res.data.reason || "No photos found matching your face.");
      } else {
        setResults(res.data.matches);
      }
    } catch (e) {
      setError("Error during search: " + e.message);
    } finally {
      setSearching(false);
    }
  };

  if (error && (!results || results.length === 0)) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-6 text-center font-sans">
        <div className="bg-red-100 p-6 rounded-full mb-6">
          <AlertCircle size={48} className="text-red-600" />
        </div>
        <h2 className="text-3xl font-black text-gray-900 mb-2">No Matches Found</h2>
        <p className="text-gray-500 mb-10 max-w-sm">{error}</p>
        <div className="flex flex-col gap-3 w-full max-w-xs">
          <button 
            onClick={() => { setError(null); setResults(null); setShowCapture(true); }} 
            className="w-full py-4 bg-purple-600 text-white rounded-2xl font-black shadow-lg shadow-purple-100"
          >
            Try Guided Search
          </button>
          <button 
            onClick={() => window.location.reload()} 
            className="w-full py-4 bg-white text-gray-900 border-2 border-gray-100 rounded-2xl font-black"
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 font-sans text-gray-900">
      <header className="bg-white border-b border-gray-200 py-6 px-6 sticky top-0 z-10 shadow-sm">
        <div className="max-w-2xl mx-auto flex justify-between items-center">
          <div>
            <h1 className="text-xl font-black text-purple-600 uppercase tracking-tighter">Pixamatch</h1>
            <p className="text-xs text-gray-500 font-bold uppercase tracking-widest">{basketInfo?.name || "Loading..."}</p>
          </div>
          {results && results.length > 0 && (
            <button onClick={() => setResults(null)} className="text-sm font-bold text-purple-600">New Search</button>
          )}
        </div>
      </header>

      <main className="max-w-2xl mx-auto p-6">
        {showCapture && (
          <div className="fixed inset-0 z-50 bg-gray-900/90 backdrop-blur-sm flex flex-col items-center justify-center p-4">
            <button 
              onClick={() => setShowCapture(false)}
              className="absolute top-6 right-6 p-3 bg-white/10 text-white rounded-full hover:bg-white/20 transition"
            >
              <X size={24} />
            </button>
            <div className="w-full max-w-md">
              <SelfieCapture onComplete={onSelfieComplete} />
            </div>
          </div>
        )}

        {!results && !searching && !showCapture && (
          <div className="text-center py-12">
            <div className="bg-purple-100 w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-8">
              <Sparkles className="text-purple-600" size={40} />
            </div>
            <h2 className="text-3xl font-black mb-4 tracking-tight">Find your photos!</h2>
            <p className="text-gray-500 mb-10 text-lg">Guided capture will help us find you in every lighting and angle.</p>
            
            <div className="space-y-4">
              <button 
                onClick={() => setShowCapture(true)}
                className="w-full py-4 bg-purple-600 text-white rounded-2xl font-black text-xl shadow-lg shadow-purple-200 cursor-pointer hover:bg-purple-700 active:scale-95 transition"
              >
                <div className="flex items-center justify-center gap-3">
                  <Camera size={28} /> Start Guided Search
                </div>
              </button>
              
              <label className="block w-full py-4 bg-white text-gray-900 border-2 border-gray-200 rounded-2xl font-bold text-lg cursor-pointer hover:bg-gray-50 transition">
                <input type="file" accept="image/*" className="hidden" onChange={onFileUpload} />
                <div className="flex items-center justify-center gap-3">
                  <Upload size={24} /> Quick Upload
                </div>
              </label>
            </div>
            
            <p className="mt-12 text-xs text-gray-400 font-medium">Your photo is processed locally and never stored. Privacy first.</p>
          </div>
        )}

        {searching && (
          <div className="text-center py-24">
            <div className="relative w-32 h-32 mx-auto mb-10">
              <div className="absolute inset-0 border-8 border-purple-100 rounded-full"></div>
              <div className="absolute inset-0 border-8 border-purple-600 rounded-full border-t-transparent animate-spin"></div>
            </div>
            <h2 className="text-2xl font-black mb-2">Analyzing...</h2>
            <p className="text-gray-500 animate-pulse">Fusion matching across 3 specialized indices</p>
          </div>
        )}

        {results && results.length > 0 && (
          <div>
            <div className="mb-8">
              <h2 className="text-2xl font-black">We found you in {results.length} photos! 🎉</h2>
              <p className="text-gray-500 text-sm">Matches verified via coarse-to-fine fusion.</p>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              {results.map((res, i) => (
                <div key={i} className="group relative rounded-2xl overflow-hidden shadow-md bg-white border border-gray-100 aspect-square">
                  <img src={res.image_url} alt="Match" className="w-full h-full object-cover group-hover:scale-110 transition duration-500" />
                  
                  {DEBUG && (
                    <div className="absolute top-2 right-2 bg-black/60 backdrop-blur-md text-white text-[10px] font-black px-2 py-1 rounded-full z-10 border border-white/20">
                      {(res.score * 100).toFixed(1)}%
                    </div>
                  )}

                  <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-20 transition flex items-center justify-center opacity-0 group-hover:opacity-100">
                    <a href={res.image_url} download className="bg-white p-3 rounded-full text-purple-600 shadow-xl" target="_blank" rel="noreferrer">
                      <Download size={24} />
                    </a>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-12 flex gap-4">
               <button className="flex-1 py-4 bg-gray-900 text-white rounded-2xl font-black flex items-center justify-center gap-2">
                 <Download size={20} /> Download All
               </button>
               <button className="px-6 py-4 bg-white border-2 border-gray-200 text-gray-900 rounded-2xl font-black">
                 <Share2 size={20} />
               </button>
            </div>
          </div>
        )}
      </main>
      
      {basketInfo && basketInfo.faces_indexed < 10 && !results && !searching && (
         <div className="fixed bottom-6 left-6 right-6 bg-amber-50 border border-amber-200 p-4 rounded-xl flex gap-3 items-center shadow-lg">
            <div className="bg-amber-100 p-2 rounded-lg text-amber-600 font-bold text-[10px] uppercase">Wait</div>
            <p className="text-xs text-amber-800 font-medium">This basket is still processing. Check back later for more results!</p>
         </div>
      )}
    </div>
  );
}

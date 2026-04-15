import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { Camera, Upload, Sparkles, Download, Share2 } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function Viewer() {
  const { basket_id } = useParams();
  const [basketInfo, setBasketInfo] = useState(null);
  const [searching, setSearching] = useState(false);
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

  const onSelfieUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setSearching(true);
    setResults(null);
    setError(null);

    const formData = new FormData();
    formData.append('selfie', file);

    try {
      const res = await axios.post(`${API_BASE}/baskets/${basket_id}/search`, formData);
      setResults(res.data.matches);
      if (res.data.no_match) setError(res.data.reason || "No photos found matching your face.");
    } catch (e) {
      setError("Error during search: " + e.message);
    } finally {
      setSearching(false);
    }
  };

  if (error && !results) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-6 text-center font-sans">
        <h2 className="text-2xl font-bold text-red-600 mb-2">Oops!</h2>
        <p className="text-gray-600 mb-6">{error}</p>
        <button onClick={() => window.location.reload()} className="px-6 py-2 bg-purple-600 text-white rounded-lg font-bold">Try Again</button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 font-sans text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 py-6 px-6 sticky top-0 z-10 shadow-sm">
        <div className="max-w-2xl mx-auto flex justify-between items-center">
          <div>
            <h1 className="text-xl font-black text-purple-600 uppercase tracking-tighter">Pixamatch</h1>
            <p className="text-xs text-gray-500 font-bold uppercase tracking-widest">{basketInfo?.name || "Loading..."}</p>
          </div>
          {results && (
            <button onClick={() => setResults(null)} className="text-sm font-bold text-purple-600">New Search</button>
          )}
        </div>
      </header>

      <main className="max-w-2xl mx-auto p-6">
        {!results && !searching && (
          <div className="text-center py-12">
            <div className="bg-purple-100 w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-8">
              <Sparkles className="text-purple-600" size={40} />
            </div>
            <h2 className="text-3xl font-black mb-4 tracking-tight">Find your photos!</h2>
            <p className="text-gray-500 mb-10 text-lg">Upload a selfie and we'll scan the event gallery to find every photo you're in.</p>
            
            <div className="space-y-4">
              <label className="block w-full py-4 bg-purple-600 text-white rounded-2xl font-black text-xl shadow-lg shadow-purple-200 cursor-pointer hover:bg-purple-700 active:scale-95 transition">
                <input type="file" accept="image/*" capture="user" className="hidden" onChange={onSelfieUpload} />
                <div className="flex items-center justify-center gap-3">
                  <Camera size={28} /> Take a Selfie
                </div>
              </label>
              
              <label className="block w-full py-4 bg-white text-gray-900 border-2 border-gray-200 rounded-2xl font-bold text-lg cursor-pointer hover:bg-gray-50 transition">
                <input type="file" accept="image/*" className="hidden" onChange={onSelfieUpload} />
                <div className="flex items-center justify-center gap-3">
                  <Upload size={24} /> Upload from Library
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
            <p className="text-gray-500 animate-pulse">Scanning {basketInfo?.faces_indexed || "all"} indexed faces</p>
          </div>
        )}

        {results && (
          <div>
            <div className="mb-8">
              <h2 className="text-2xl font-black">We found you in {results.length} photos! 🎉</h2>
              <p className="text-gray-500 text-sm">Tap a photo to view or download.</p>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              {results.map((res, i) => (
                <div key={i} className="group relative rounded-2xl overflow-hidden shadow-md bg-white border border-gray-100 aspect-square">
                  <img src={res.image_url} alt="Match" className="w-full h-full object-cover group-hover:scale-110 transition duration-500" />
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

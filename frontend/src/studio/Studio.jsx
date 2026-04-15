import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useDropzone } from 'react-dropzone';
import { Folder, Upload, Link, QrCode, CheckCircle, RefreshCcw } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function Studio() {
  const [baskets, setBaskets] = useState([]);
  const [activeBasket, setActiveBasket] = useState(null);
  const [progress, setProgress] = useState(null);
  const [showQR, setShowQR] = useState(false);

  useEffect(() => {
    const fetchBaskets = async () => {
      try {
        const res = await axios.get(`${API_BASE}/baskets`);
        setBaskets(res.data.baskets);
      } catch (e) {
        console.error("Error fetching baskets", e);
      }
    };
    fetchBaskets();
  }, []);

  const createBasket = async () => {
    const name = prompt("Basket Name:");
    if (!name) return;
    try {
      const res = await axios.post(`${API_BASE}/baskets`, { name });
      const newBasket = { ...res.data, name };
      setBaskets([...baskets, newBasket]);
      setActiveBasket(newBasket);
    } catch (e) {
      alert("Error creating basket: " + e.message);
    }
  };

  const onDrop = async (acceptedFiles) => {
    if (!activeBasket) return;
    const formData = new FormData();
    acceptedFiles.forEach(file => formData.append('images', file));
    try {
      await axios.post(`${API_BASE}/baskets/${activeBasket.basket_id}/images`, formData);
    } catch (e) {
      alert("Error uploading images: " + e.message);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  useEffect(() => {
    let interval;
    if (activeBasket) {
      interval = setInterval(async () => {
        try {
          const res = await axios.get(`${API_BASE}/baskets/${activeBasket.basket_id}/progress`);
          setProgress(res.data);
        } catch (e) {
          console.error("Progress fetch error", e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [activeBasket]);

  const copyLink = () => {
    if (!activeBasket) return;
    navigator.clipboard.writeText(activeBasket.share_url);
    alert("Share link copied!");
  };

  const selectBasket = async (basket) => {
    try {
      const res = await axios.get(`${API_BASE}/baskets/${basket.id}/info`);
      // Mix core basket ID/URL with detailed info
      setActiveBasket({
        basket_id: basket.id,
        share_url: `${window.location.origin}/find/${basket.id}`,
        ...res.data
      });
    } catch (e) {
      console.error("Error fetching basket info", e);
    }
  };

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 font-sans">
      {/* Sidebar */}
      <div className="w-64 bg-white border-r border-gray-200 p-4 flex flex-col">
        <h1 className="text-xl font-bold mb-6 flex items-center gap-2">
          <Folder className="text-purple-600" /> Pixamatch
        </h1>
        <button 
          onClick={createBasket}
          className="w-full py-2 bg-purple-600 text-white rounded-lg mb-4 hover:bg-purple-700 transition font-medium"
        >
          + New Basket
        </button>
        <div className="flex-1 overflow-y-auto space-y-1">
          {baskets.map(b => (
            <button 
              key={b.id}
              onClick={() => selectBasket(b)}
              className={`w-full text-left px-3 py-2 rounded-md transition text-sm ${activeBasket?.basket_id === b.id ? 'bg-purple-100 text-purple-700 font-bold' : 'hover:bg-gray-100'}`}
            >
              {b.name || "Untitled"}
            </button>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 p-8 overflow-y-auto">
        {activeBasket ? (
          <div className="max-w-4xl mx-auto">
            <div className="flex justify-between items-center mb-8">
              <div>
                <h2 className="text-3xl font-extrabold tracking-tight">{activeBasket.name}</h2>
                <p className="text-gray-500 text-sm mt-1">ID: {activeBasket.basket_id}</p>
              </div>
              <div className="flex gap-3">
                <button 
                  onClick={copyLink}
                  className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-white bg-gray-50 transition shadow-sm font-medium"
                >
                  <Link size={18} /> Share Link
                </button>
                <button 
                  onClick={() => setShowQR(true)}
                  className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-white bg-gray-50 transition shadow-sm font-medium"
                >
                  <QrCode size={18} /> QR Code
                </button>
              </div>
            </div>

            {/* Dropzone */}
            <div 
              {...getRootProps()} 
              className={`border-4 border-dashed rounded-2xl p-20 text-center transition-all cursor-pointer ${isDragActive ? 'border-purple-500 bg-purple-50 shadow-inner' : 'border-gray-300 bg-white hover:border-gray-400'}`}
            >
              <input {...getInputProps()} />
              <div className="bg-purple-100 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-6">
                <Upload className="text-purple-600" size={32} />
              </div>
              <p className="text-xl font-bold">Drop images here or browse files</p>
              <p className="text-gray-500 mt-2">JPG, PNG, HEIC — up to 50 photos at once</p>
            </div>

            {/* Progress */}
            {progress && progress.total > 0 && (
              <div className="mt-8 bg-white p-8 rounded-2xl shadow-lg border border-gray-100">
                <div className="flex justify-between items-end mb-4">
                  <div>
                    <h3 className="font-bold text-lg">Ingestion Status</h3>
                    <p className="text-gray-500 text-sm">{progress.done} of {progress.total} images processed</p>
                  </div>
                  <span className="text-2xl font-black text-purple-600">{Math.round((progress.done / progress.total) * 100)}%</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-4 mb-6 overflow-hidden">
                  <div 
                    className="bg-purple-600 h-full transition-all duration-500 ease-out" 
                    style={{ width: `${(progress.done / progress.total) * 100}%` }}
                  ></div>
                </div>
                <div className="grid grid-cols-3 gap-6 pt-6 border-t border-gray-50">
                   <div className="text-center">
                     <p className="text-2xl font-bold text-green-600">{progress.done}</p>
                     <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold mt-1">Processed</p>
                   </div>
                   <div className="text-center">
                     <p className="text-2xl font-bold text-red-600">{progress.failed || 0}</p>
                     <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold mt-1">Failed</p>
                   </div>
                   <div className="text-center">
                     <p className="text-2xl font-bold text-purple-700">{progress.faces_indexed}</p>
                     <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold mt-1">Faces Indexed</p>
                   </div>
                </div>
              </div>
            )}

            {/* QR Modal */}
            {showQR && (
              <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                <div className="bg-white p-10 rounded-3xl max-w-sm w-full text-center shadow-2xl">
                  <h3 className="text-2xl font-bold mb-6">Scan to Search</h3>
                  <div className="bg-gray-50 p-6 rounded-2xl inline-block mb-6 border border-gray-100">
                    <QRCodeSVG value={activeBasket.share_url} size={200} />
                  </div>
                  <p className="text-sm text-gray-500 mb-8 px-4">Place this QR at your event for guests to find their photos.</p>
                  <button 
                    onClick={() => setShowQR(false)}
                    className="w-full py-3 bg-gray-900 text-white rounded-xl font-bold hover:bg-black transition"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-gray-400">
            <div className="bg-gray-100 w-24 h-24 rounded-full flex items-center justify-center mb-6">
              <Folder size={48} className="opacity-20" />
            </div>
            <p className="text-xl font-medium">Select or create a basket to get started</p>
            <p className="text-gray-400 text-sm mt-2">All your indexed photos in one secure place</p>
          </div>
        )}
      </div>
    </div>
  );
}

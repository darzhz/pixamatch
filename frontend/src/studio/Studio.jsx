import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { useDropzone } from 'react-dropzone';
import { Folder, Upload, Link, QrCode, CheckCircle, RefreshCcw, Loader2, Image as ImageIcon, Trash2, Menu, X, Share2 } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import Folders from './Folders';


export default function Studio() {
  const [baskets, setBaskets] = useState([]);
  const [activeBasket, setActiveBasket] = useState(null);
  const [progress, setProgress] = useState(null);
  const [showQR, setShowQR] = useState(false);
  const [clientProgress, setClientProgress] = useState({ done: 0, total: 0, status: 'idle' });
  const [images, setImages] = useState([]);
  const [nextMarker, setNextMarker] = useState(null);
  const [loadingImages, setLoadingImages] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [view, setView] = useState('gallery'); // 'gallery' | 'folders'
  
  const observer = useRef();
  const lastImageRef = useCallback(node => {
    if (loadingImages) return;
    if (observer.current) observer.current.disconnect();
    observer.current = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && nextMarker) {
        fetchImages(activeBasket.basket_id, nextMarker);
      }
    });
    if (node) observer.current.observe(node);
  }, [loadingImages, nextMarker, activeBasket]);

  const fetchBaskets = async () => {
    try {
      const res = await axios.get(`/api/baskets`);
      setBaskets(res.data.baskets);
    } catch (e) {
      console.error("Error fetching baskets", e);
    }
  };

  useEffect(() => {
    fetchBaskets();
  }, []);

  const fetchImages = async (basketId, marker = null, reset = false) => {
    setLoadingImages(true);
    try {
      const res = await axios.get(`/api/baskets/${basketId}/images`, {
        params: { marker, limit: 24 }
      });
      if (reset) {
        setImages(res.data.images);
      } else {
        setImages(prev => [...prev, ...res.data.images]);
      }
      setNextMarker(res.data.next_marker);
    } catch (e) {
      console.error("Error fetching images", e);
    } finally {
      setLoadingImages(false);
    }
  };

  const createBasket = async () => {
    const name = prompt("Basket Name:");
    if (!name) return;
    try {
      const res = await axios.post(`/api/baskets`, { name });
      const newBasket = { ...res.data, name };
      setBaskets([...baskets, newBasket]);
      setActiveBasket(newBasket);
      setIsSidebarOpen(false);
    } catch (e) {
      alert("Error creating basket: " + e.message);
    }
  };

  const deleteBasket = async (id, e) => {
    if (e) e.stopPropagation();
    if (!confirm("Are you sure you want to delete this basket? All images and data will be permanently removed.")) return;
    
    try {
      await axios.delete(`/api/baskets/${id}`);
      setBaskets(prev => prev.filter(b => b.id !== id));
      if (activeBasket?.basket_id === id) {
        setActiveBasket(null);
        setImages([]);
      }
    } catch (err) {
      alert("Error deleting basket: " + err.message);
    }
  };

  const deleteImage = async (key) => {
    if (!confirm("Delete this image? It will be removed from storage and vector search.")) return;
    try {
      await axios.delete(`/api/baskets/${activeBasket.basket_id}/images`, {
        params: { key }
      });
      setImages(prev => prev.filter(img => img.key !== key));
      // Update local faces count estimate
      if (activeBasket) {
        setActiveBasket(prev => ({
          ...prev,
          image_count: Math.max(0, (prev.image_count || 0) - 1)
        }));
      }
    } catch (e) {
      alert("Error deleting image: " + e.message);
    }
  };

  const processImage = async (file) => {
    const shouldCompress = import.meta.env.VITE_COMPRESS_STUDIO !== 'false';
    if (!shouldCompress) return file;

    try {
      const bitmap = await createImageBitmap(file);
      const maxSize = 1280;
      let width = bitmap.width;
      let height = bitmap.height;

      if (width > height) {
        if (width > maxSize) {
          height *= maxSize / width;
          width = maxSize;
        }
      } else {
        if (height > maxSize) {
          width *= maxSize / height;
          height = maxSize;
        }
      }

      const canvas = new OffscreenCanvas(width, height);
      const ctx = canvas.getContext('2d');
      ctx.drawImage(bitmap, 0, 0, width, height);
      // Quality 0.85 provides a huge size reduction with minimal visual loss
      const blob = await canvas.convertToBlob({ type: 'image/webp', quality: 0.85 });
      return new File([blob], file.name.replace(/\.[^/.]+$/, "") + ".webp", { type: 'image/webp' });
    } catch (err) {
      console.error("Compression error", err);
      return file; // fallback to original
    }
  };

  const onDrop = async (acceptedFiles) => {
    if (!activeBasket) return;
    setClientProgress({ done: 0, total: acceptedFiles.length, status: 'compressing' });
    
    const uploadBatchSize = 10; // Safer batch size
    const concurrency = 3;
    let currentBatch = [];
    
    for (let i = 0; i < acceptedFiles.length; i += concurrency) {
      const chunk = acceptedFiles.slice(i, i + concurrency);
      const results = await Promise.all(chunk.map(processImage));
      currentBatch.push(...results);
      
      setClientProgress(prev => ({ 
        ...prev, 
        done: Math.min(i + concurrency, acceptedFiles.length),
        status: 'compressing'
      }));

      if (currentBatch.length >= uploadBatchSize || i + concurrency >= acceptedFiles.length) {
        setClientProgress(prev => ({ ...prev, status: 'uploading' }));
        const formData = new FormData();
        currentBatch.forEach(file => formData.append('images', file));
        try {
          await axios.post(`/api/baskets/${activeBasket.basket_id}/images`, formData);
        } catch (e) {
          console.error("Upload error", e);
        }
        currentBatch = []; // Clear memory immediately
      }
    }
    
    setClientProgress({ done: 0, total: 0, status: 'idle' });
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  useEffect(() => {
    let eventSource;
    if (activeBasket) {
      eventSource = new EventSource(`/api/baskets/${activeBasket.basket_id}/progress/events`);
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setProgress(data);
          // Refresh gallery when ingestion progress updates
          if (data.done > 0 && data.done % 10 === 0) {
             // Optional: trigger a partial refresh or just wait for scroll
          }
        } catch (e) {
          console.error("Error parsing progress event", e);
        }
      };
      eventSource.onerror = (e) => {
        console.error("EventSource failed", e);
        eventSource.close();
      };
    }
    return () => {
      if (eventSource) eventSource.close();
    };
  }, [activeBasket]);

  const copyLink = () => {
    if (!activeBasket) return;
    navigator.clipboard.writeText(activeBasket.share_url);
    alert("Share link copied!");
  };

  const generateCullLink = async () => {
    if (!activeBasket) return;
    try {
      const res = await axios.post(`/api/baskets/${activeBasket.basket_id}/cull-links`, {});
      navigator.clipboard.writeText(res.data.url);
      alert("Culling link generated and copied to clipboard!");
    } catch (e) {
      console.error("Error generating cull link", e);
    }
  };

  const selectBasket = async (basket) => {
    try {
      const res = await axios.get(`/api/baskets/${basket.id}/info`);
      // Mix core basket ID/URL with detailed info
      setActiveBasket({
        basket_id: basket.id,
        share_url: `${window.location.origin}/find/${basket.id}`,
        ...res.data
      });
      setImages([]);
      setNextMarker(null);
      fetchImages(basket.id, null, true);
      setIsSidebarOpen(false);
      setView('gallery');
    } catch (e) {
      console.error("Error fetching basket info", e);
    }
  };

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 font-sans overflow-hidden">
      {/* Sidebar Backdrop for Mobile */}
      {isSidebarOpen && (
        <div 
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={`
        fixed inset-y-0 left-0 w-64 bg-white border-r border-gray-200 p-4 flex flex-col z-50 transition-transform duration-300 ease-in-out md:relative md:translate-x-0
        ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        <div className="flex items-center justify-between mb-6 md:block">
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Folder className="text-purple-600" /> Pixamatch
          </h1>
          <button 
            className="md:hidden p-2 hover:bg-gray-100 rounded-lg"
            onClick={() => setIsSidebarOpen(false)}
          >
            <X size={20} />
          </button>
        </div>

        <button 
          onClick={createBasket}
          className="w-full py-2 bg-purple-600 text-white rounded-lg mb-4 hover:bg-purple-700 transition font-medium shadow-md"
        >
          + New Basket
        </button>
        <div className="flex-1 overflow-y-auto space-y-1">
          {baskets.map(b => (
            <div 
              key={b.id} 
              className={`group flex items-center justify-between px-3 py-2 rounded-md transition text-sm cursor-pointer ${activeBasket?.basket_id === b.id ? 'bg-purple-100 text-purple-700 font-bold' : 'hover:bg-gray-100'}`}
              onClick={() => selectBasket(b)}
            >
              <span className="truncate flex-1">{b.name || "Untitled"}</span>
              <button 
                onClick={(e) => deleteBasket(b.id, e)}
                className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-600 transition"
                title="Delete Basket"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Mobile Header */}
        <header className="md:hidden bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between shrink-0">
          <h1 className="text-lg font-bold flex items-center gap-2">
            <Folder className="text-purple-600" size={18} /> Pixamatch
          </h1>
          <button 
            onClick={() => setIsSidebarOpen(true)}
            className="p-2 hover:bg-gray-100 rounded-lg"
          >
            <Menu size={24} />
          </button>
        </header>

        <div className="flex-1 p-4 md:p-8 overflow-y-auto">
          {activeBasket ? (
            <div className="max-w-4xl mx-auto">
              <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 gap-4">
                <div>
                  <h2 className="text-2xl md:text-3xl font-extrabold tracking-tight">{activeBasket.name}</h2>
                  <p className="text-gray-500 text-sm mt-1">ID: {activeBasket.basket_id}</p>
                </div>
                <div className="flex flex-wrap gap-2 md:gap-3">
                  <button 
                    onClick={generateCullLink}
                    className="flex-1 md:flex-none flex items-center justify-center gap-2 px-3 py-2 border border-purple-200 text-purple-600 rounded-lg hover:bg-purple-50 transition shadow-sm font-medium text-sm md:text-base"
                  >
                    <Share2 size={16} /> Share Culling Link
                  </button>
                  <button 
                    onClick={copyLink}
                    className="flex-1 md:flex-none flex items-center justify-center gap-2 px-3 py-2 border border-gray-300 rounded-lg hover:bg-white bg-gray-50 transition shadow-sm font-medium text-sm md:text-base"
                  >
                    <Link size={16} /> Share
                  </button>
                  <button 
                    onClick={() => setShowQR(true)}
                    className="flex-1 md:flex-none flex items-center justify-center gap-2 px-3 py-2 border border-gray-300 rounded-lg hover:bg-white bg-gray-50 transition shadow-sm font-medium text-sm md:text-base"
                  >
                    <QrCode size={16} /> QR Code
                  </button>
                  <button 
                    onClick={() => deleteBasket(activeBasket.basket_id)}
                    className="flex-1 md:flex-none flex items-center justify-center gap-2 px-3 py-2 border border-red-200 text-red-600 rounded-lg hover:bg-red-50 transition shadow-sm font-medium text-sm md:text-base"
                  >
                    <Trash2 size={16} /> Delete
                  </button>
                </div>
              </div>

              {/* View Toggles */}
              <div className="flex gap-4 mb-8 border-b border-gray-200">
                <button 
                  onClick={() => setView('gallery')}
                  className={`pb-4 text-sm font-bold transition-all px-2 ${view === 'gallery' ? 'text-purple-600 border-b-2 border-purple-600' : 'text-gray-400 hover:text-gray-600'}`}
                >
                  Gallery
                </button>
                <button 
                  onClick={() => setView('folders')}
                  className={`pb-4 text-sm font-bold transition-all px-2 ${view === 'folders' ? 'text-purple-600 border-b-2 border-purple-600' : 'text-gray-400 hover:text-gray-600'}`}
                >
                  Submissions
                </button>
              </div>

              {view === 'gallery' ? (
                <>
                  {/* Dropzone */}
                  <div 
                    {...getRootProps()} 
                    className={`border-4 border-dashed rounded-2xl p-10 md:p-20 text-center transition-all cursor-pointer ${isDragActive ? 'border-purple-500 bg-purple-50 shadow-inner' : 'border-gray-300 bg-white hover:border-gray-400'}`}
                  >
                    <input {...getInputProps()} />
                    <div className="bg-purple-100 w-12 h-12 md:w-16 md:h-16 rounded-full flex items-center justify-center mx-auto mb-4 md:mb-6">
                      <Upload className="text-purple-600" size={24} md:size={32} />
                    </div>
                    <p className="text-lg md:text-xl font-bold">Drop images here or browse</p>
                    <p className="text-gray-500 text-sm mt-2">JPG, PNG, WEBP — up to 1000 photos</p>
                  </div>

                  {/* Client-Side Progress (Compression/Upload) */}
                  {clientProgress.status !== 'idle' && (
                    <div className="mt-6 md:mt-8 bg-purple-600 text-white p-4 md:p-6 rounded-2xl shadow-lg animate-in slide-in-from-bottom-4 duration-300">
                      <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-3">
                          <Loader2 className="animate-spin" size={20} md:size={24} />
                          <span className="font-bold md:text-lg capitalize">{clientProgress.status}...</span>
                        </div>
                        <span className="font-black">{Math.round((clientProgress.done / clientProgress.total) * 100)}%</span>
                      </div>
                      <div className="w-full bg-white/20 rounded-full h-2 overflow-hidden">
                        <div 
                          className="bg-white h-full transition-all duration-300" 
                          style={{ width: `${(clientProgress.done / clientProgress.total) * 100}%` }}
                        ></div>
                      </div>
                      <p className="text-xs md:text-sm mt-3 opacity-90">Processing {clientProgress.done} of {clientProgress.total} files locally</p>
                    </div>
                  )}

                  {/* Ingestion Progress */}
                  {progress && progress.total > 0 && (
                    <div className="mt-6 md:mt-8 bg-white p-6 md:p-8 rounded-2xl shadow-lg border border-gray-100">
                      <div className="flex justify-between items-end mb-4">
                        <div>
                          <h3 className="font-bold md:text-lg">Server Ingestion</h3>
                          <p className="text-gray-500 text-sm">{progress.done} of {progress.total} images indexed</p>
                        </div>
                        <span className="text-xl md:text-2xl font-black text-purple-600">{Math.round((progress.done / progress.total) * 100)}%</span>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-3 md:h-4 mb-6 overflow-hidden">
                        <div 
                          className="bg-purple-600 h-full transition-all duration-500 ease-out" 
                          style={{ width: `${(progress.done / progress.total) * 100}%` }}
                        ></div>
                      </div>

                      {/* Error Display */}
                      {progress.last_error && (
                        <div className="mb-6 p-4 bg-red-50 border border-red-100 rounded-xl flex gap-3 items-start animate-pulse">
                          <RefreshCcw className="text-red-500 shrink-0 mt-0.5" size={18} />
                          <div className="text-sm">
                            <p className="font-bold text-red-800">Recent Error</p>
                            <p className="text-red-600 leading-snug">{progress.last_error}</p>
                          </div>
                        </div>
                      )}

                      <div className="grid grid-cols-3 gap-3 md:gap-6 pt-6 border-t border-gray-50">
                        <div className="text-center">
                          <p className="text-xl md:text-2xl font-bold text-green-600">{progress.done}</p>
                          <p className="text-[10px] md:text-xs text-gray-500 uppercase tracking-widest font-semibold mt-1">Processed</p>
                        </div>
                        <div className="text-center">
                          <p className="text-xl md:text-2xl font-bold text-red-600">{progress.failed || 0}</p>
                          <p className="text-[10px] md:text-xs text-gray-500 uppercase tracking-widest font-semibold mt-1">Failed</p>
                        </div>
                        <div className="text-center">
                          <p className="text-xl md:text-2xl font-bold text-purple-700">{progress.faces_indexed}</p>
                          <p className="text-[10px] md:text-xs text-gray-500 uppercase tracking-widest font-semibold mt-1">Faces Indexed</p>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Gallery Section */}
                  <div className="mt-8 md:mt-12">
                    <div className="flex items-center justify-between mb-6">
                      <h3 className="text-lg md:text-xl font-bold flex items-center gap-2">
                        <ImageIcon className="text-purple-600" size={18} md:size={20} />
                        Basket Photos
                      </h3>
                      <span className="text-gray-500 text-xs md:text-sm">{images.length} photos loaded</span>
                    </div>
                    
                    {images.length > 0 ? (
                      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 md:gap-4">
                        {images.map((img, index) => (
                          <div 
                            key={img.key} 
                            ref={index === images.length - 1 ? lastImageRef : null}
                            className="aspect-square rounded-xl overflow-hidden bg-gray-200 border border-gray-100 group relative shadow-sm"
                          >
                            <img 
                              src={img.url} 
                              alt="Basket item" 
                              loading="lazy"
                              className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                            />
                            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100">
                               <button 
                                 onClick={() => deleteImage(img.key)}
                                 className="p-3 bg-red-600 text-white rounded-full shadow-xl hover:bg-red-700 hover:scale-110 transition-all active:scale-95"
                                 title="Delete Image"
                               >
                                  <Trash2 size={20} />
                               </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : !loadingImages && (
                      <div className="bg-white rounded-2xl p-8 md:p-12 text-center border border-gray-100 border-dashed">
                        <p className="text-gray-400 text-sm md:text-base">No photos in this basket yet.</p>
                      </div>
                    )}
                    
                    {loadingImages && (
                      <div className="flex justify-center py-8">
                        <Loader2 className="animate-spin text-purple-600" size={32} />
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <Folders basketId={activeBasket.basket_id} />
              )}

              {/* QR Modal */}
              {showQR && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                  <div className="bg-white p-6 md:p-10 rounded-3xl max-w-sm w-full text-center shadow-2xl animate-in fade-in zoom-in duration-300">
                    <h3 className="text-xl md:text-2xl font-bold mb-6">Scan to Search</h3>
                    <div className="bg-gray-50 p-4 md:p-6 rounded-2xl inline-block mb-6 border border-gray-100">
                      <QRCodeSVG value={activeBasket.share_url} size={window.innerWidth < 640 ? 150 : 200} />
                    </div>
                    <p className="text-sm text-gray-500 mb-8 px-2 md:px-4">Place this QR at your event for guests to find their photos.</p>
                    <button 
                      onClick={() => setShowQR(false)}
                      className="w-full py-3 bg-gray-900 text-white rounded-xl font-bold hover:bg-black transition shadow-lg"
                    >
                      Close
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-gray-400 p-4 text-center">
              <div className="bg-gray-100 w-20 h-20 md:w-24 md:h-24 rounded-full flex items-center justify-center mb-6">
                <Folder size={40} md:size={48} className="opacity-20" />
              </div>
              <p className="text-lg md:text-xl font-medium">Select or create a basket</p>
              <p className="text-gray-400 text-sm mt-2 max-w-xs">All your indexed photos in one secure place</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

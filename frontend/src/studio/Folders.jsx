import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Folder, Clock, CheckCircle, ExternalLink, Download, Loader2 } from 'lucide-react';

export default function Folders({ basketId }) {
  const [folders, setFolders] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchFolders = async () => {
    try {
      const res = await axios.get(`/api/baskets/${basketId}/folders`);
      setFolders(res.data.folders);
    } catch (e) {
      console.error("Error fetching folders", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (basketId) fetchFolders();
  }, [basketId]);

  const markRead = async (folderId) => {
    try {
      await axios.patch(`/api/folders/${folderId}/read`);
      setFolders(prev => prev.map(f => f.id === folderId ? { ...f, is_new: false } : f));
    } catch (e) {
      console.error("Error marking folder as read", e);
    }
  };

  if (loading) return <Loader2 className="animate-spin mx-auto mt-10" />;

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <h3 className="text-xl font-bold flex items-center gap-2">
          <Folder className="text-purple-600" /> Client Selections
        </h3>
        <span className="text-gray-500 text-sm">{folders.length} folders</span>
      </div>

      {folders.length === 0 ? (
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-2xl p-10 text-center">
          <p className="text-gray-400">No client submissions yet.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {folders.map(folder => (
            <div 
              key={folder.id}
              onClick={() => markRead(folder.id)}
              className={`bg-white rounded-2xl p-5 border shadow-sm transition-all hover:shadow-md cursor-pointer relative group ${folder.is_new ? 'border-purple-500 ring-1 ring-purple-500' : 'border-gray-100'}`}
            >
              {folder.is_new && (
                <span className="absolute top-4 right-4 bg-purple-600 text-white text-[10px] font-black px-2 py-0.5 rounded-full uppercase tracking-tighter animate-bounce">
                  New
                </span>
              )}

              <div className="flex items-start gap-4 mb-4">
                <div className="bg-purple-50 w-12 h-12 rounded-xl flex items-center justify-center shrink-0">
                  <Folder className="text-purple-600" />
                </div>
                <div>
                  <h4 className="font-bold text-gray-900 group-hover:text-purple-700 transition-colors">{folder.name}</h4>
                  <div className="flex items-center gap-2 text-xs text-gray-400 mt-1">
                    <Clock size={12} />
                    {new Date(folder.created_at).toLocaleDateString()}
                  </div>
                </div>
              </div>

              {/* Preview Images */}
              <div className="grid grid-cols-4 gap-2 mb-4">
                {folder.previews.map((url, i) => (
                  <div key={i} className="aspect-square rounded-lg overflow-hidden bg-gray-100">
                    <img src={url} className="w-full h-full object-cover" alt="" />
                  </div>
                ))}
                {folder.image_paths.length > 4 && (
                  <div className="aspect-square rounded-lg bg-gray-50 flex items-center justify-center text-[10px] font-bold text-gray-400 border border-gray-100">
                    +{folder.image_paths.length - 4}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between pt-4 border-t border-gray-50">
                <span className="text-xs font-bold text-gray-500">{folder.image_paths.length} Photos</span>
                <div className="flex gap-2">
                   <button className="p-2 hover:bg-gray-50 rounded-lg text-gray-400 hover:text-purple-600 transition-colors" title="Download List">
                      <Download size={16} />
                   </button>
                   <button className="p-2 hover:bg-gray-50 rounded-lg text-gray-400 hover:text-purple-600 transition-colors" title="Open Pipeline">
                      <ExternalLink size={16} />
                   </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Studio from './studio/Studio';
import Viewer from './viewer/Viewer';
import CullView from './viewer/CullView';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/studio" element={<Studio />} />
        <Route path="/find/:basket_id" element={<Viewer />} />
        <Route path="/cull/:basket_id/:token" element={<CullView />} />
        <Route path="*" element={<Navigate to="/studio" replace />} />
      </Routes>
    </Router>
  );
}

export default App;

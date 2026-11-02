import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { AccountPage, accountPaths, accountsEnabled } from './AccountPage';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{accountsEnabled && accountPaths.includes(window.location.pathname) ? <AccountPage /> : <App />}</React.StrictMode>,
);

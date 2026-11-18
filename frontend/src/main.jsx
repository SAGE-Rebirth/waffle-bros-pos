import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { ConfigProvider } from './config.jsx';
import './styles.css';

createRoot(document.getElementById('root')).render(
  <ConfigProvider>
    <App />
  </ConfigProvider>,
);

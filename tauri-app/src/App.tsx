import { useEffect, useState } from "react";
import Login from "./components/Login";
import FileBrowser from "./components/FileBrowser";
import { isLoggedIn } from "./lib/accelerator/auth";
import "./App.css";

function App() {
  // null = "still checking stored credentials" so Login doesn't flash
  // before a stored refresh token has been looked up.
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null);

  useEffect(() => {
    isLoggedIn().then(setLoggedIn);
  }, []);

  if (loggedIn === null) {
    return <main className="container" />;
  }

  return loggedIn ? (
    <FileBrowser onLoggedOut={() => setLoggedIn(false)} />
  ) : (
    <Login onLoggedIn={() => setLoggedIn(true)} />
  );
}

export default App;

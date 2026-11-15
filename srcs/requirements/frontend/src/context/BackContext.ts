import { createContext, useContext } from "react";

/** "Back" action of the signed-in screens (null on the home screen): shown next to the sheet title. */
export const BackContext = createContext<(() => void) | null>(null);

export const useBack = () => useContext(BackContext);

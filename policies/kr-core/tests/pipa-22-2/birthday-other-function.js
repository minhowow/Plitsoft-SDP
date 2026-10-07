import api from "./client";

export const signUp = (email, password, nickname) => api.post("/auth/signup", { email, password, nickname });

export const login = (email, password) => api.post("/auth/login", { email, password });

export const updateProfile = (nickname, birthday) => api.patch("/me", { nickname, birthday });

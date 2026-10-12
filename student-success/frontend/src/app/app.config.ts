import { ApplicationConfig, provideAppInitializer, provideBrowserGlobalErrorListeners, provideZonelessChangeDetection, inject } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { PreloadAllModules, provideRouter, withComponentInputBinding, withNavigationErrorHandler, withPreloading } from '@angular/router';

import { routes } from './app.routes';
import { authInterceptor } from './core/auth.interceptor';
import { AuthService } from './core/auth.service';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    // After a new version is deployed, an open tab may ask for page files that no longer exist:
    // reload once to pick up the new version instead of showing an error.
    // pages load their code in the background after sign-in, so moving between pages never waits for a download
    provideRouter(routes, withComponentInputBinding(), withPreloading(PreloadAllModules), withNavigationErrorHandler((e) => {
      const msg = String((e.error as Error)?.message || e.error);
      if (!/dynamically imported module|Importing a module script failed|ChunkLoadError/i.test(msg)) return;
      const key = 'ssp.reloaded';
      try {
        if (sessionStorage.getItem(key) === e.url) return;  // already tried once for this page
        sessionStorage.setItem(key, e.url);
      } catch { /* storage unavailable: still reload */ }
      location.assign(e.url);
    })),
    provideHttpClient(withInterceptors([authInterceptor])),
    provideAppInitializer(() => inject(AuthService).init().catch(() => undefined)),
  ],
};

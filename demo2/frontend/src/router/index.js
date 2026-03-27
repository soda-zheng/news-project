import { createRouter, createWebHistory } from 'vue-router'
import HomePage from '../pages/HomePage.vue'
import VideosPage from '../pages/VideosPage.vue'
import HotTopicsRoutePage from '../pages/HotTopicsRoutePage.vue'
import ResearchPage from '../pages/ResearchPage.vue'
import FinancialReportPage from '../pages/FinancialReportPageImpl.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomePage },
    { path: '/videos', name: 'videos', component: VideosPage },
    { path: '/hot-topics', name: 'hot-topics', component: HotTopicsRoutePage },
    { path: '/research', name: 'research', component: ResearchPage },
    { path: '/financial-report', name: 'financial-report', component: FinancialReportPage },
    // 未匹配路径回首页，避免出现「空白页」（App 里无 router-view 时仅靠 name 判断）
    { path: '/:pathMatch(.*)*', redirect: { name: 'home' } },
  ],
})

export default router


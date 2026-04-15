<template>
  <div>
    <div class="market-data">
      <div class="market-title"><div>实时行情</div></div>
      <div class="market-row">
        <div class="market-item" v-for="m in markets" :key="m.name">
          <div class="market-name">{{ m.name }}</div>
          <div class="market-value">{{ m.price }}</div>
          <div class="market-change" :class="m.chg > 0 ? 'up' : (m.chg < 0 ? 'down' : '')">
            {{ formatSigned(m.chg) }} ({{ formatSigned(m.pct_chg) }}%)
          </div>
        </div>
      </div>
    </div>

    <div class="hot-news">
      <div class="section-title">热点新闻</div>
      <div v-if="newsErr" class="result result-error">
        {{ newsErr }}
      </div>
      <div class="featured-wrap">
        <div class="featured-grid">
          <div class="featured-card clickable" v-for="n in featuredNews" :key="n.id" @click="$emit('open-url', n.url)">
            <div class="featured-img"><img class="featured-img-el" :src="n.picUrl" alt="" loading="lazy" /></div>
            <div class="featured-body">
              <div class="featured-title">{{ n.title }}</div>
              <div class="featured-meta"><span class="tag">热</span><span class="muted">{{ formatTime(n.ctime * 1000) }}</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="main-container">
      <div class="news-section">
        <div class="section-title">要点新闻</div>
        <div class="news-item clickable" v-for="n in myNews" :key="n.id" @click="$emit('open-url', n.url)">
          <div class="news-content">
            <div class="news-author"><span class="news-cat">{{ n.category || '市场关注' }}</span><span class="news-time">{{ formatTime(n.ctime * 1000) }}</span></div>
            <div class="news-desc"><b>{{ n.title }}</b></div>
            <div class="muted news-summary">{{ n.summary }}</div>
          </div>
        </div>
      </div>

      <div class="right-section">
        <div class="hot-topics">
          <div class="video-header">
            <div class="section-title">今日涨幅榜 Top10（股票）</div>
            <div class="video-more" @click="$emit('goto-hot-topics')">更多</div>
          </div>
          <ul class="topic-list">
            <li class="topic-item clickable" v-for="(t, idx) in hotTopics" :key="t.name + idx" @click="$emit('pick-topic', t)">
              <span class="topic-num">{{ idx + 1 }}</span>
              <span class="topic-text">{{ t.name }}<span class="muted" v-if="t.leader"> · 代码：{{ t.leader }}</span></span>
              <span class="topic-pct" :class="(t.pct_chg ?? 0) > 0 ? 'up' : ((t.pct_chg ?? 0) < 0 ? 'down' : '')">{{ formatSigned(t.pct_chg ?? 0) }}%</span>
            </li>
          </ul>
        </div>

        <div class="video-section">
          <div class="video-header">
            <div class="section-title">视频专区</div>
            <div class="video-more" @click="$emit('goto-videos')">更多视频</div>
          </div>
          <ul class="video-list">
            <li class="video-item clickable" v-for="v in videos.slice(0, 3)" :key="v.id" @click="$emit('play-video', v)">
              <div class="video-thumbnail"><img :src="v.cover" alt="" loading="lazy" /></div>
              <div class="video-info">
                <div class="video-title" :title="v.title">{{ summarizeVideoTitle(v.title) }}</div>
                <div class="muted video-meta">
                  <span v-if="v.tag">{{ v.tag }}</span><span v-if="v.duration">{{ v.duration }}</span><span v-if="v.type === 'external'">站外</span>
                </div>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ markets: Array, newsErr: String, featuredNews: Array, myNews: Array, hotTopics: Array, videos: Array, formatSigned: Function, formatTime: Function, summarizeVideoTitle: Function })
defineEmits(['open-url', 'pick-topic', 'play-video', 'goto-videos', 'goto-hot-topics'])
</script>


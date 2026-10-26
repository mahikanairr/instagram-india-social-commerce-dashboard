import os
import pandas as pd
import streamlit as st
import plotly.express as px
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title='India Social Commerce Intelligence', page_icon='📊', layout='wide')
st.title('Instagram India · Social Commerce Intelligence')
st.caption('Monitored public Instagram content · sample-based intelligence, not platform-wide market totals')
# Rerun open browser sessions every 5 minutes. Cached API reads expire after 300 seconds.
st_autorefresh(interval=300000, limit=None, key='auto_refresh_5m')

try:
    import requests
    endpoint = st.secrets['apps_script_url']
    reader_secret = st.secrets['dashboard_read_secret']

    @st.cache_data(ttl=300, show_spinner='Loading private Google Sheets data…')
    def load_sheet(sheet, _url, _secret):
        all_rows = []
        columns = None
        for page in range(1000):
            response = requests.post(_url, json={
                'action': 'read', 'sheet': sheet, 'page': page,
                'secret': _secret
            }, timeout=45)
            response.raise_for_status()
            result = response.json()
            if not result.get('ok'):
                raise RuntimeError(result.get('error', 'Reader returned an error'))
            if columns is None: columns = result['columns']
            all_rows.extend(result.get('rows', []))
            if not result.get('has_more'): break
        else:
            raise RuntimeError('Worksheet exceeded maximum page count')
        return pd.DataFrame(all_rows, columns=columns)

    posts = load_sheet('Posts', endpoint, reader_secret)
    tags = load_sheet('Hashtag_Candidates', endpoint, reader_secret)
    history = load_sheet('Query_History', endpoint, reader_secret)
    try:
        engagement_history = load_sheet('Engagement_History', endpoint, reader_secret)
        engagement_error = None
    except Exception as eng_err:
        engagement_history = pd.DataFrame()
        engagement_error = str(eng_err)
    try:
        ingestion_log = load_sheet('Ingestion_Log', endpoint, reader_secret)
        ingestion_log_error = None
    except Exception as log_err:
        ingestion_log = pd.DataFrame()
        ingestion_log_error = str(log_err)
except Exception as err:
    st.error('Could not load the private Google Sheet. Check the Apps Script deployment and Streamlit secrets.')
    st.code(str(err)); st.stop()

if posts.empty:
    st.info('No posts imported yet.');st.stop()
for col in ['Likes','Comments','Video_Views']:
    posts[col]=pd.to_numeric(posts.get(col),errors='coerce')
posts['Published_Date']=pd.to_datetime(posts.get('Published_Date'),errors='coerce')
posts['Observation_Date']=pd.to_datetime(posts.get('Observation_Date'),errors='coerce')
posts['Post_ID']=posts['Post_ID'].astype('string').str.replace(r'\.0$','',regex=True)
posts=posts.drop_duplicates(subset=['Post_ID'],keep='last')

# Show auditable ingestion activity. Distinguish successful database uploads from
# Instagram observation dates (which are different measurements).
st.subheader('Data freshness and pipeline')
fresh_a, fresh_b, fresh_c = st.columns(3)
obs = posts['Observation_Date'].max()
fresh_a.metric('Latest observation', obs.strftime('%d %b %Y') if pd.notna(obs) else 'Not recorded')

if not ingestion_log.empty and 'Status' in ingestion_log.columns:
    log = ingestion_log.copy()
    log['At'] = pd.to_datetime(log.get('At'), errors='coerce')
    log = log.sort_values('At', ascending=False, na_position='last')
    successful = log[log['Status'].astype(str).str.upper().eq('OK')]
    recent = log.iloc[0]
    if not successful.empty and pd.notna(successful.iloc[0]['At']):
        fresh_b.metric('Last successful upload', successful.iloc[0]['At'].strftime('%d %b %Y %H:%M'))
    else:
        fresh_b.metric('Last successful upload', 'Not recorded')
    status = str(recent.get('Status','Unknown')).upper()
    fresh_c.metric('Latest receiver result', status)
    if status != 'OK':
        st.warning('Latest recorded receiver attempt did not report OK. Review upload logs.')
    with st.expander('Recent Google Sheets ingestion log'):
        st.dataframe(log.head(15), use_container_width=True, hide_index=True)
else:
    fresh_b.metric('Last successful upload', 'Not available')
    fresh_c.metric('Latest receiver result', 'Not available')
    st.caption('Ingestion log unavailable: enable Ingestion_Log in the Apps Script read allowlist.')
st.caption('Open dashboard sessions refresh every 5 minutes. Last upload refers to the receiver log, not necessarily the last successful AllyHub search. Weekly collection status requires separate scheduled-run reporting.')


with st.sidebar:
    st.header('Filters')
    cats=sorted(posts['Product_Category'].dropna().astype(str).unique().tolist())
    category=st.multiselect('Product category',cats)
    geos=sorted(posts['Geo_Confidence'].dropna().astype(str).unique().tolist())
    geo=st.multiselect('Geographic evidence',geos)
    statuses=sorted(posts['Content_Relevance_Class'].dropna().astype(str).unique().tolist())
    relevance=st.multiselect('Product relevance',statuses)
    if st.button('Refresh data now'):
        st.cache_data.clear();st.rerun()

df=posts.copy()
if category:df=df[df['Product_Category'].isin(category)]
if geo:df=df[df['Geo_Confidence'].isin(geo)]
if relevance:df=df[df['Content_Relevance_Class'].isin(relevance)]

latest=df['Observation_Date'].max()
a,b,c,d=st.columns(4)
a.metric('Unique posts',f'{df.Post_ID.nunique():,}')
b.metric('Creators',f'{df.Creator_Handle.nunique():,}')
c.metric('Categories',f'{df.Product_Category.nunique():,}')
d.metric('Last observed',latest.strftime('%d %b %Y') if pd.notna(latest) else 'Historical')

t1,t2,t3,t4,t5=st.tabs(['Overview','Weekly discovery','Hashtags','Post explorer','Engagement intelligence'])
with t1:
    c1,c2=st.columns(2)
    with c1:
        counts=df.groupby('Product_Category',dropna=False).size().reset_index(name='Collected posts').sort_values('Collected posts',ascending=False)
        st.plotly_chart(px.bar(counts,x='Collected posts',y='Product_Category',orientation='h',title='Collected posts by product category'),use_container_width=True)
    with c2:
        geo_counts=df['Geo_Confidence'].fillna('Unknown').value_counts().rename_axis('Evidence').reset_index(name='Posts')
        st.plotly_chart(px.bar(geo_counts,x='Evidence',y='Posts',title='Geographic evidence coverage'),use_container_width=True)
    period=df.dropna(subset=['Published_Date']).copy()
    period['Month']=period['Published_Date'].dt.to_period('M').astype(str)
    months=period.groupby(['Month','Product_Category']).size().reset_index(name='Posts')
    st.plotly_chart(px.line(months,x='Month',y='Posts',color='Product_Category',markers=True,title='Observed publication dates (collection is not exhaustive)'),use_container_width=True)
with t2:
    recent=df[df['Observation_Date'].notna()].copy()
    st.subheader('Newly collected post records')
    st.caption('This counts observed records, not all posts published on Instagram in the week.')
    if recent.empty: st.info('No ingestion observations yet.')
    else:
        weekly=recent.groupby(recent['Observation_Date'].dt.strftime('%Y-%m-%d')).agg(Posts=('Post_ID','nunique'),Creators=('Creator_Handle','nunique')).reset_index().rename(columns={'Observation_Date':'Observation day'})
        st.dataframe(weekly,use_container_width=True,hide_index=True)
    if not history.empty:
        st.subheader('Search audit')
        st.dataframe(history,use_container_width=True,hide_index=True)
with t3:
    st.caption('Hashtags new to our monitored dataset are not necessarily new or trending on Instagram.')
    if not tags.empty:
        st.dataframe(tags,use_container_width=True,hide_index=True)
    else: st.info('No hashtag candidate batches imported yet.')
    counts={}
    for v in df['Hashtags'].dropna().astype(str):
        for tag in set(x.strip().lower().lstrip('#') for x in v.replace(' ',' ,').split(',') if x.strip()):
            if tag and tag!='nan':counts[tag]=counts.get(tag,0)+1
    if counts:
        hc=pd.DataFrame([{'Hashtag':'#'+k,'Posts':v} for k,v in counts.items()]).sort_values('Posts',ascending=False).head(25)
        st.plotly_chart(px.bar(hc,x='Posts',y='Hashtag',orientation='h',title='Top observed hashtags in filtered records'),use_container_width=True)
with t4:
    columns=[c for c in ['Post_ID','Post_URL','Published_Date','Creator_Handle','Product_Category','Content_Relevance_Class','Geo_Confidence','Creator_State','Likes','Comments','Video_Views','Content_Format','Exact_Query'] if c in df.columns]
    st.dataframe(df[columns],hide_index=True,use_container_width=True,column_config={'Post_URL':st.column_config.LinkColumn('Instagram post')})
    st.download_button('Download filtered posts CSV',df[columns].to_csv(index=False).encode('utf-8-sig'),file_name='instagram_filtered_posts.csv',mime='text/csv')


with t5:
    st.subheader('Instagram engagement intelligence')
    st.caption('Observed engagement for monitored posts only. These are snapshots taken at different post ages, not platform-wide totals or repeat-measured growth.')
    edf = df.copy()
    edf['Observed_Interactions'] = edf[['Likes', 'Comments']].fillna(0).sum(axis=1)
    post_n = len(edf)
    n_likes = int(edf['Likes'].notna().sum())
    n_comments = int(edf['Comments'].notna().sum())
    n_views = int(edf['Video_Views'].notna().sum())
    m1,m2,m3,m4 = st.columns(4)
    m1.metric('Observed likes', f"{edf['Likes'].sum():,.0f}")
    m2.metric('Observed comments', f"{edf['Comments'].sum():,.0f}")
    m3.metric('Observed interactions', f"{edf['Observed_Interactions'].sum():,.0f}")
    m4.metric('Posts with view counts', f'{n_views:,} / {post_n:,}')
    st.caption(f'Metric availability — likes: {n_likes:,}/{post_n:,}; comments: {n_comments:,}/{post_n:,}; video views: {n_views:,}/{post_n:,}. Missing values are excluded from metric averages; views are not interpreted as zero.')

    category_stats = edf.groupby('Product_Category', dropna=False).agg(
        Posts=('Post_ID','nunique'),
        Likes_observed=('Likes','sum'), Comments_observed=('Comments','sum'),
        Posts_with_likes=('Likes','count'), Posts_with_comments=('Comments','count'),
        Posts_with_views=('Video_Views','count'), Views_observed=('Video_Views','sum')
    ).reset_index()
    category_stats['Avg_likes_per_measured_post'] = category_stats['Likes_observed'] / category_stats['Posts_with_likes'].replace(0, float('nan'))
    category_stats['Avg_comments_per_measured_post'] = category_stats['Comments_observed'] / category_stats['Posts_with_comments'].replace(0, float('nan'))
    category_stats['Likes_coverage_pct'] = (100 * category_stats['Posts_with_likes'] / category_stats['Posts']).round(1)
    category_stats['Views_coverage_pct'] = (100 * category_stats['Posts_with_views'] / category_stats['Posts']).round(1)
    metric_choice = st.selectbox('Compare categories by', ['Average likes per measured post', 'Average comments per measured post', 'Total observed likes', 'Total observed comments', 'Posts with video views'], key='engagement_category_metric')
    metric_map = {'Average likes per measured post':'Avg_likes_per_measured_post','Average comments per measured post':'Avg_comments_per_measured_post','Total observed likes':'Likes_observed','Total observed comments':'Comments_observed','Posts with video views':'Posts_with_views'}
    chosen=metric_map[metric_choice]
    show_cat=category_stats.sort_values(chosen,ascending=True)
    st.plotly_chart(px.bar(show_cat,x=chosen,y='Product_Category',orientation='h',hover_data=['Posts','Likes_coverage_pct','Views_coverage_pct'],title=f'{metric_choice} · observed sample'),use_container_width=True)
    with st.expander('Category engagement and measurement coverage',expanded=False):
        st.dataframe(category_stats.sort_values('Posts',ascending=False),hide_index=True,use_container_width=True)

    a,b=st.columns(2)
    with a:
        st.markdown('#### Highest-engagement observed posts')
        top_posts=edf.sort_values('Observed_Interactions',ascending=False).head(20)
        top_columns=[x for x in ['Post_URL','Creator_Handle','Product_Category','Published_Date','Likes','Comments','Video_Views','Observed_Interactions'] if x in top_posts.columns]
        st.dataframe(top_posts[top_columns],hide_index=True,use_container_width=True,column_config={'Post_URL':st.column_config.LinkColumn('Open post')})
    with b:
        st.markdown('#### Creators in the monitored sample')
        creator_stats=edf.groupby('Creator_Handle',dropna=False).agg(
            Posts=('Post_ID','nunique'),Observed_interactions=('Observed_Interactions','sum'),Likes=('Likes','sum'),Comments=('Comments','sum')
        ).reset_index()
        creator_stats['Interactions_per_observed_post'] = creator_stats['Observed_interactions']/creator_stats['Posts'].replace(0,float('nan'))
        st.dataframe(creator_stats.sort_values('Observed_interactions',ascending=False).head(20),hide_index=True,use_container_width=True)

    st.markdown('#### Weekly and monthly performance')
    st.caption('Compare posts by the week or month they were published. Likes and comments are available snapshots, not weekly increases on those same posts. Older posts may have had more time to gain engagement.')
    periods = edf.dropna(subset=['Published_Date']).copy()
    if periods.empty:
        st.info('Publication dates are unavailable, so weekly/monthly comparisons cannot be calculated.')
    else:
        interval, measure = st.columns([1, 1])
        with interval:
            frequency = st.radio('Group posts by', ['Month', 'Week'], horizontal=True, key='engagement_grouping')
        with measure:
            chosen_measure = st.selectbox('Compare using', ['Median likes per measured post', 'Median comments per measured post', 'Posts published'], key='engagement_time_metric')
        # Calendar-aligned buckets, not observation/collection dates.
        period_code = 'W-SUN' if frequency == 'Week' else 'M'
        periods['_period'] = periods['Published_Date'].dt.to_period(period_code)
        periods['_period_start'] = periods['_period'].dt.start_time
        periods['_period_label'] = periods['_period'].astype(str)
        periods['_metric'] = pd.to_numeric(periods['Likes'] if chosen_measure.startswith('Median likes') else periods['Comments'], errors='coerce')
        agg = periods.groupby(['_period_start', '_period_label'], as_index=False).agg(
            Posts=('Post_ID', 'nunique'),
            Creators=('Creator_Handle', 'nunique'),
            Measured_posts=('_metric', 'count'),
            Median_engagement=('_metric', 'median')
        ).sort_values('_period_start')
        if chosen_measure == 'Posts published':
            agg['Plot_value'] = agg['Posts']
            plot_label = 'Posts published in collected sample'
        else:
            # Require a few comparable measurements instead of amplifying 1-post outliers.
            agg['Plot_value'] = agg['Median_engagement'].where(agg['Measured_posts'] >= 3)
            plot_label = chosen_measure
        total_buckets = len(agg)
        if total_buckets > 24:
            # Keep the trend readable; the full-period table is retained below.
            chart_agg = agg.tail(24)
            st.caption(f'Showing the most recent 24 {frequency.lower()}s in the chart; all {total_buckets} periods remain in the table.')
        else:
            chart_agg = agg
        ca, cb, cc = st.columns(3)
        ca.metric('Posts with publication dates', f"{len(periods):,}")
        cb.metric('Time periods', f"{total_buckets:,}")
        cc.metric('Metric coverage', f"{int(periods['_metric'].notna().sum()):,} / {len(periods):,}" if chosen_measure != 'Posts published' else 'Not required')
        if chart_agg['Plot_value'].notna().any():
            fig = px.bar(chart_agg, x='_period_label', y='Plot_value',
                         custom_data=['Posts', 'Measured_posts', 'Creators'],
                         labels={'_period_label':f'Publication {frequency.lower()}', 'Plot_value':plot_label},
                         title=plot_label)
            fig.update_traces(hovertemplate='<b>%{x}</b><br>Value: %{y:,.0f}<br>Posts: %{customdata[0]}<br>Measured posts: %{customdata[1]}<br>Creators: %{customdata[2]}<extra></extra>')
            fig.update_layout(xaxis_tickangle=-35, showlegend=False, margin=dict(t=55,b=55))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info('At least three measured posts per period are needed for a reliable comparison. Try Monthly or Posts published.')
        if chosen_measure != 'Posts published':
            st.caption('Periods with fewer than 3 posts having this metric are hidden from the chart. Median reduces the influence of unusually viral posts.')
        # Focus on the most recent period with available data, retaining sample sizes.
        latest_bucket = agg['_period_start'].max()
        by_category = periods[periods['_period_start'] == latest_bucket].groupby('Product_Category', dropna=False).agg(
            Posts=('Post_ID','nunique'), Creators=('Creator_Handle','nunique'),
            Measured_posts=('_metric','count'), Median_engagement=('_metric','median')
        ).reset_index()
        by_category['Coverage_pct'] = (100 * by_category['Measured_posts'] / by_category['Posts'].replace(0, float('nan'))).round(0)
        by_category['Median_engagement'] = by_category['Median_engagement'].where(by_category['Measured_posts']>=3)
        if chosen_measure == 'Posts published':
            by_category = by_category.sort_values('Posts',ascending=False)
        else:
            by_category = by_category.sort_values('Median_engagement',ascending=False,na_position='last')
        st.markdown(f"##### Categories in the latest publication {frequency.lower()}: {agg.iloc[-1]['_period_label']}")
        st.caption('A blank median means fewer than three measured posts in that category during this period. This is not market share.')
        shown = by_category.rename(columns={'Product_Category':'Category', 'Measured_posts':'Posts with metric',
                                            'Median_engagement':'Median likes/comments', 'Coverage_pct':'Metric coverage (%)'})
        columns = ['Category','Posts','Creators'] if chosen_measure == 'Posts published' else ['Category','Posts','Posts with metric','Median likes/comments','Metric coverage (%)']
        st.dataframe(shown[columns], use_container_width=True, hide_index=True)
        with st.expander('View all periods and measurement coverage'):
            st.dataframe(agg[['_period_label','Posts','Creators','Measured_posts','Median_engagement']].rename(
                columns={'_period_label':'Publication period','Measured_posts':'Posts with metric',
                         'Median_engagement':'Median metric'}).sort_values('Publication period',ascending=False),
                hide_index=True,use_container_width=True)
        st.caption('These are comparisons between different publishing cohorts, not the growth of a fixed set of posts. For genuine same-post changes, use Engagement Growth below.')

    st.markdown('#### Engagement Growth')
    st.caption('A small pilot tracking the same Instagram posts over time. This is not an estimate for all 15 categories.')
    if engagement_history.empty:
        st.info('Engagement_History is not connected or contains no observations yet. Existing engagement charts above continue to work.')
        if engagement_error:
            st.caption('History read status: '+engagement_error)
    else:
        eh = engagement_history.copy()
        eh['Post_ID'] = eh['Post_ID'].astype('string').str.strip()
        eh['Observation_Date'] = pd.to_datetime(eh['Observation_Date'], errors='coerce')
        for mc in ['Likes','Comments','Video_Views']:
            eh[mc] = pd.to_numeric(eh[mc].replace('', pd.NA), errors='coerce')
        eh = eh.drop_duplicates(subset=['obs_key'], keep='last')
        if category:
            eh = eh[eh['Product_Category'].isin(category)]
        if eh.empty:
            st.info('No tracked engagement history for the selected category.')
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric('Posts tracked', int(eh['Post_ID'].nunique()))
            c2.metric('Observations', len(eh))
            c3.metric('Categories covered', int(eh['Product_Category'].nunique()))

            # One digestible row per post. Only compare metric values when the
            # observations were recorded on different calendar dates.
            summaries=[]
            for pid, group in eh.groupby('Post_ID'):
                group=group.sort_values(['Observation_Date','Observed_At_UTC'],na_position='first')
                last=group.iloc[-1]
                row={'Creator':str(last['Creator_Handle']),'Category':str(last['Product_Category']),
                     'Observations':len(group),'Last checked':last['Observation_Date'].strftime('%d %b %Y') if pd.notna(last['Observation_Date']) else 'Unknown',
                     '_post_id':str(pid)}
                for metric in ['Likes','Comments']:
                    valid=group.dropna(subset=['Observation_Date',metric])
                    if len(valid):
                        latest=valid.iloc[-1]
                        row['Latest '+metric.lower()]=int(latest[metric])
                        older=valid[valid['Observation_Date'].dt.date < latest['Observation_Date'].date()]
                        row[metric+' change']=int(latest[metric]-older.iloc[-1][metric]) if len(older) else None
                    else:
                        row['Latest '+metric.lower()]=None
                        row[metric+' change']=None
                summaries.append(row)
            overview=pd.DataFrame(summaries).sort_values('Creator')
            st.markdown('##### Latest engagement by creator')
            st.caption('Change compares the latest value with a measurement from an earlier day. A dash means there are not yet two comparable dates.')
            showcols=['Creator','Category','Last checked','Latest likes','Likes change','Latest comments','Comments change']
            st.dataframe(overview[showcols],hide_index=True,use_container_width=True,
                         column_config={'Latest likes':st.column_config.NumberColumn(format='%d'),
                                        'Likes change':st.column_config.NumberColumn(format='%+d'),
                                        'Latest comments':st.column_config.NumberColumn(format='%d'),
                                        'Comments change':st.column_config.NumberColumn(format='%+d')})
            st.markdown('##### Explore one tracked post')
            options={f"{r['Creator']} · {r['Category']}":r['_post_id'] for r in summaries}
            selected=st.selectbox('Choose a creator to see their history',options=list(options),
                                  index=0,key='engagement_post_detail')
            post=eh[eh['Post_ID']==options[selected]].sort_values(['Observation_Date','Observed_At_UTC'])
            metric=st.radio('Measure', ['Likes','Comments','Video_Views'],horizontal=True,key='engagement_detail_metric')
            chart=post.dropna(subset=['Observation_Date',metric]).copy()
            if chart.empty:
                st.info(f'No {metric.lower().replace("_", " ")} observations available for this post.')
            else:
                chart['Measured on']=chart['Observation_Date'].dt.strftime('%d %b %Y')
                # A table remains readable with sparse, mixed-precision observations.
                # Date-only records do not imply a precise collection time.
                display=chart[['Measured on','Time_Precision',metric]].rename(columns={'Time_Precision':'Time accuracy'})
                st.dataframe(display,hide_index=True,use_container_width=True)
                if chart['Observation_Date'].dt.date.nunique() >= 2:
                    fig=px.line(chart,x='Observation_Date',y=metric,markers=True,
                                title=f'{metric.replace("_", " ")} over observation dates',
                                hover_data=['Time_Precision'])
                    fig.update_layout(xaxis_title='Date measured',yaxis_title=metric.replace('_',' '))
                    st.plotly_chart(fig,use_container_width=True)
                else:
                    st.caption('A trend line will appear when this post has measurements on at least two different dates.')
            with st.expander('View detailed engagement records'):
                st.dataframe(eh[['Post_ID','Creator_Handle','Product_Category','Observation_Date','Time_Precision',
                                 'Likes','Comments','Video_Views','Retrieval_Status','Method']]
                             .sort_values('Observation_Date',ascending=False),
                             use_container_width=True,hide_index=True)

    st.download_button('Download category engagement analysis',category_stats.to_csv(index=False).encode('utf-8-sig'),file_name='instagram_engagement_category_analysis.csv',mime='text/csv')

st.divider()
st.caption('Source: historical Instagram snapshots plus AllyHub discovery. Likes/comments may be measured at different ages; missing views are not zero. Geography requires explicit evidence.')

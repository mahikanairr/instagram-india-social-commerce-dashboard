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

t1,t2,t3,t4=st.tabs(['Overview','Weekly discovery','Hashtags','Post explorer'])
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

st.divider()
st.caption('Source: historical Instagram snapshots plus AllyHub discovery. Likes/comments may be measured at different ages; missing views are not zero. Geography requires explicit evidence.')

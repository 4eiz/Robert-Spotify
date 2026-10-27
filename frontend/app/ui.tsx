'use client';

import { useEffect, useState, type SelectHTMLAttributes } from 'react';
import { Copy, Eye, EyeOff, LoaderCircle, Check, ChevronDown } from 'lucide-react';

export function SelectControl({children,...props}: SelectHTMLAttributes<HTMLSelectElement>) {
  return <span className="select-control"><select {...props}>{children}</select><ChevronDown size={16} strokeWidth={1.75} aria-hidden="true"/></span>;
}

export function SpotifyIcon({size=24}: {size?:number}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" role="img" aria-label="Spotify"><path d="M12 0a12 12 0 1 0 0 24 12 12 0 0 0 0-24Zm5.503 17.31a.748.748 0 0 1-1.028.249c-2.819-1.722-6.367-2.112-10.546-1.157a.747.747 0 1 1-.333-1.457c4.573-1.045 8.495-.595 11.66 1.338a.748.748 0 0 1 .247 1.027Zm1.469-3.266a.936.936 0 0 1-1.287.308c-3.226-1.983-8.142-2.557-11.956-1.399a.936.936 0 0 1-.543-1.792c4.357-1.322 9.773-.682 13.478 1.595a.935.935 0 0 1 .308 1.288Zm.126-3.403C15.23 8.344 8.849 8.133 5.156 9.254a1.122 1.122 0 1 1-.652-2.147c4.24-1.287 11.287-1.038 15.737 1.604a1.122 1.122 0 0 1-1.143 1.93Z"/></svg>;
}

export function Skeleton({section=false}: {section?:boolean}) {
  return <div className={'skeleton-screen '+(section?'section-skeleton':'')} role="status" aria-live="polite" aria-label="Загрузка данных"><span className="sr-only">Загружаем кабинет…</span>{!section&&<><div className="skeleton-sidebar"><div className="skeleton sk-brand"/>{Array.from({length:6},(_,i)=><div key={i} className="skeleton sk-nav"/>)}</div><div className="skeleton-topbar"/></>}<div className="skeleton-content"><div className="skeleton sk-eyebrow"/><div className="skeleton sk-title"/><div className="skeleton sk-subtitle"/><div className="skeleton-stats">{Array.from({length:4},(_,i)=><div className="sk-panel" key={i}><div className="skeleton sk-line"/><div className="skeleton sk-number"/><div className="skeleton sk-line short"/></div>)}</div><div className="skeleton-columns">{[0,1].map(i=><div className="sk-panel" key={i}><div className="skeleton sk-line short"/>{Array.from({length:4},(_,j)=><div key={j} className="sk-row"><div className="skeleton sk-avatar"/><div className="skeleton sk-line"/></div>)}</div>)}</div></div></div>;
}

export function OwnerPassword({memberId,hasPassword,fetchPassword,onError}: {memberId:number;hasPassword:boolean;fetchPassword:()=>Promise<string>;onError:(message:string)=>void}) {
  const [value,setValue]=useState<string|null>(null),[busy,setBusy]=useState(false),[copied,setCopied]=useState(false);
  useEffect(()=>{setValue(null);setCopied(false);},[memberId]);
  useEffect(()=>{if(value===null)return;const clear=()=>setValue(null);const timer=setTimeout(clear,30000);const hide=()=>{if(document.hidden)clear();};document.addEventListener('visibilitychange',hide);window.addEventListener('blur',clear);return()=>{clearTimeout(timer);document.removeEventListener('visibilitychange',hide);window.removeEventListener('blur',clear);};},[value]);
  useEffect(()=>{if(!copied)return;const timer=setTimeout(()=>setCopied(false),2500);return()=>clearTimeout(timer);},[copied]);
  async function act(copy:boolean){setBusy(true);try{const password=await fetchPassword();if(!password){onError('Пароль владельца не задан. Добавь его в карточке участника.');return;}if(copy){await navigator.clipboard.writeText(password);setCopied(true);}else setValue(password);}catch{onError(copy?'Не удалось скопировать пароль. Проверь разрешение буфера обмена.':'Не удалось получить пароль. Обнови страницу и повтори вход.');}finally{setBusy(false);}}
  return <><label className="read-label" htmlFor="owner-password">Пароль аккаунта</label><div className="copy-field owner-password"><input id="owner-password" aria-label="Пароль владельца" type={value===null?'password':'text'} readOnly value={hasPassword?(value??'••••••••••••'):''} placeholder="Пароль не задан" autoComplete="off" spellCheck={false}/><button className="icon-button" aria-label={value===null?'Показать пароль владельца':'Скрыть пароль владельца'} disabled={busy||!hasPassword} onClick={()=>value===null?act(false):setValue(null)}>{busy?<LoaderCircle size={16} className="spin"/>:value===null?<Eye size={16}/>:<EyeOff size={16}/>}</button><button className="icon-button" aria-label={copied?'Пароль скопирован':'Скопировать пароль владельца'} title={copied?'Скопировано':'Скопировать пароль'} disabled={busy||!hasPassword} onClick={()=>act(true)}>{copied?<Check size={16}/>:<Copy size={16}/>}</button></div><small className="password-hint">{copied?'Пароль скопирован':value!==null?'Скроется через 30 секунд':'Показать или скопировать одним нажатием'}</small></>;
}

export function addMonths(start:string,months:number) {
  const d=new Date(start+'T12:00:00');const day=d.getDate();d.setDate(1);d.setMonth(d.getMonth()+months);
  d.setDate(Math.min(day,new Date(d.getFullYear(),d.getMonth()+1,0).getDate()));
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

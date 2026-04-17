import React, { useState, useRef, useCallback, useEffect } from 'react';
import { GoogleGenAI, LiveServerMessage } from '@google/genai';
import { liveServiceConfiguration } from './resources/live_service_configuration';
import { decode, createBlob } from './services/audioUtils';

const LIVE_API_MODEL_NAME = 'gemini-live-2.5-flash-native-audio';

type Theme = 'light' | 'dark' | 'system';

const App: React.FC = () => {
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [isConnecting, setIsConnecting] = useState<boolean>(false);
  const [isWaitingForVideo, setIsWaitingForVideo] = useState<boolean>(false);
  const [hasVideo, setHasVideo] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Theme state
  const [theme, setTheme] = useState<Theme>('system');
  const [aspectRatio, setAspectRatio] = useState<number>(1); // Default 1:1

  // Debug Panel State
  const [showDebug, setShowDebug] = useState<boolean>(false);
  const [debugStats, setDebugStats] = useState({
    buffered: 0,
    droppedFrames: 0,
    duration: 0,
    latency: 0,
  });

  // Microphone states
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [audioDevices, setAudioDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('');

  // Audio Output states
  const [audioOutputDevices, setAudioOutputDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedAudioOutputId, setSelectedAudioOutputId] = useState<string>('');

  const sessionPromiseRef = useRef<Promise<any> | null>(null);
  const activeSessionRef = useRef<any>(null); // Holds the resolved session to prevent .then() queuing bursts
  const inputAudioContextRef = useRef<AudioContext | null>(null);
  const outputAudioContextRef = useRef<AudioContext | null>(null);
  const outputNodeRef = useRef<GainNode | null>(null);
  const videoSourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const videoAnalyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const mediaSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const hasReceivedVideoRef = useRef<boolean>(false);

  // Latency Tracking Refs
  const lastUserSpeechTimeRef = useRef<number>(0);
  const userHasSpokenForNextTurnRef = useRef<boolean>(false);
  const trackingAvatarAudioRef = useRef<boolean>(false);
  const avatarAudioStartPlayheadRef = useRef<number | null>(null);
  const avatarAudioStartPlayheadSystemTimeRef = useRef<number | null>(null);
  const latencyRef = useRef<number>(0);

  // Video & Canvas Refs
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const mseRef = useRef<MediaSource | null>(null);
  const sourceBufferRef = useRef<SourceBuffer | null>(null);
  const videoQueueRef = useRef<ArrayBuffer[]>([]);
  const cachedInitSegmentRef = useRef<ArrayBuffer | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const videoErrorListenerAddedRef = useRef<boolean>(false);

  // Theme Effect
  useEffect(() => {
    const root = window.document.documentElement;
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const applyTheme = () => {
      if (theme === 'dark' || (theme === 'system' && mediaQuery.matches)) {
        root.classList.add('dark');
      } else {
        root.classList.remove('dark');
      }
    };

    applyTheme();

    const listener = () => {
      if (theme === 'system') applyTheme();
    };

    mediaQuery.addEventListener('change', listener);
    return () => mediaQuery.removeEventListener('change', listener);
  }, [theme]);

  // Initialize Output AudioContext once to allow MediaElementAudioSourceNode creation
  useEffect(() => {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });
    outputAudioContextRef.current = ctx;
    const gain = ctx.createGain();
    gain.connect(ctx.destination);
    outputNodeRef.current = gain;

    if (videoRef.current) {
      try {
        videoSourceRef.current = ctx.createMediaElementSource(videoRef.current);
        videoAnalyserRef.current = ctx.createAnalyser();
        videoAnalyserRef.current.fftSize = 2048;
        videoSourceRef.current.connect(videoAnalyserRef.current);
        videoAnalyserRef.current.connect(gain);
      } catch (e) {
        setError("Failed to create media element source");
      }
    }

    return () => {
      ctx.close();
    };
  }, []);

  // Debug Stats Polling
  useEffect(() => {
    if (!showDebug) return;
    const interval = setInterval(() => {
      if (videoRef.current) {
        const video = videoRef.current;
        let buffered = 0;
        let duration = video.duration;
        
        if (video.buffered.length > 0) {
          const bufferedEnd = video.buffered.end(video.buffered.length - 1);
          buffered = bufferedEnd - video.currentTime;
          // Fallback for live streams where duration is Infinity or NaN
          if (isNaN(duration) || !isFinite(duration)) {
            duration = bufferedEnd;
          }
        } else if (isNaN(duration) || !isFinite(duration)) {
          duration = 0;
        }

        let droppedFrames = 0;
        if (typeof (video as any).getVideoPlaybackQuality === 'function') {
          droppedFrames = (video as any).getVideoPlaybackQuality().droppedVideoFrames;
        }
        setDebugStats({
          buffered: Math.max(0, buffered),
          droppedFrames,
          duration: duration,
          latency: latencyRef.current,
        });
      }
    }, 500);
    return () => clearInterval(interval);
  }, [showDebug]);

  // Fetch available microphones and speakers
  useEffect(() => {
    let mounted = true;
    const fetchDevices = async () => {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioInputs = devices.filter(device => device.kind === 'audioinput');
        const audioOutputs = devices.filter(device => device.kind === 'audiooutput');

        if (mounted) {
          setAudioDevices(audioInputs);
          setSelectedDeviceId(prev => {
            if (prev && audioInputs.find(d => d.deviceId === prev)) return prev;
            return (audioInputs.find(d => d.deviceId === 'default') || audioInputs[0])?.deviceId || '';
          });

          setAudioOutputDevices(audioOutputs);
          setSelectedAudioOutputId(prev => {
            if (prev && audioOutputs.find(d => d.deviceId === prev)) return prev;
            return (audioOutputs.find(d => d.deviceId === 'default') || audioOutputs[0])?.deviceId || '';
          });
        }
      } catch (e) {
        setError("Failed to fetch devices");
      }
    };

    const initDevices = async () => {
      try {
        // Request permission to get device labels
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach(t => t.stop());
      } catch (err) {
        setError("Failed to get media device permissions");
      }
      fetchDevices();
    };

    initDevices();

    navigator.mediaDevices.addEventListener('devicechange', fetchDevices);
    return () => {
      mounted = false;
      navigator.mediaDevices.removeEventListener('devicechange', fetchDevices);
    };
  }, []);

  // Apply selected audio output device to video and audio context
  useEffect(() => {
    const applyAudioOutput = async () => {
      if (!selectedAudioOutputId) return;

      if (videoRef.current && typeof (videoRef.current as any).setSinkId === 'function') {
        try {
          await (videoRef.current as any).setSinkId(selectedAudioOutputId);
        } catch (e) {
          setError("Failed to set video sink");
        }
      }

      if (outputAudioContextRef.current && typeof (outputAudioContextRef.current as any).setSinkId === 'function') {
        try {
          await (outputAudioContextRef.current as any).setSinkId(selectedAudioOutputId);
        } catch (e) {
          setError("Failed to set audio context sink");
        }
      }
    };

    applyAudioOutput();
  }, [selectedAudioOutputId, isConnected]);

  const toggleMute = useCallback(() => {
    setIsMuted(prev => {
      const newMuted = !prev;
      if (streamRef.current) {
        streamRef.current.getAudioTracks().forEach(track => {
          track.enabled = !newMuted;
        });
      }
      return newMuted;
    });
  }, []);

  const handleDeviceChange = useCallback(async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newDeviceId = e.target.value;
    setSelectedDeviceId(newDeviceId);

    if (isConnected && streamRef.current) {
      try {
        const newStream = await navigator.mediaDevices.getUserMedia({
          audio: newDeviceId ? { deviceId: { exact: newDeviceId } } : true
        });

        // Apply current mute state to new stream
        newStream.getAudioTracks().forEach(track => track.enabled = !isMuted);

        if (mediaSourceRef.current) {
          mediaSourceRef.current.disconnect();
        }
        streamRef.current.getTracks().forEach(track => track.stop());

        if (inputAudioContextRef.current && scriptProcessorRef.current) {
          const newSource = inputAudioContextRef.current.createMediaStreamSource(newStream);
          newSource.connect(scriptProcessorRef.current);
          mediaSourceRef.current = newSource;
        }
        streamRef.current = newStream;
      } catch (err) {
        setError("Failed to switch microphone.");
      }
    }
  }, [isConnected, isMuted]);

  const handleAudioOutputChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedAudioOutputId(e.target.value);
  }, []);

  const initMediaSource = useCallback(() => {
    const videoElement = videoRef.current;
    if (!videoElement) return;
    if (!window.MediaSource) {
      setError("MediaSource API not supported.");
      return;
    }
    if (mseRef.current) return;

    const mediaSource = new MediaSource();
    mseRef.current = mediaSource;
    videoElement.src = URL.createObjectURL(mediaSource);

    if (!videoErrorListenerAddedRef.current) {
      videoElement.addEventListener("error", (e) => {
        if (!mseRef.current) return;
        mseRef.current = null;
        sourceBufferRef.current = null;
        videoQueueRef.current = [];
        setError("Video playback error.");
      });
      videoErrorListenerAddedRef.current = true;
    }

    mediaSource.addEventListener("sourceopen", () => {
      try {
        let sourceBuffer = sourceBufferRef.current;
        if (!sourceBuffer) {
          const type = 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"';
          if (MediaSource.isTypeSupported(type)) {
            sourceBuffer = mediaSource.addSourceBuffer(type);
          } else {
            sourceBuffer = mediaSource.addSourceBuffer("video/mp4");
          }
          sourceBuffer.mode = "sequence";
          sourceBufferRef.current = sourceBuffer;

          const cachedInitSegment = cachedInitSegmentRef.current;
          if (cachedInitSegment && videoQueueRef.current[0] !== cachedInitSegment) {
            videoQueueRef.current.unshift(cachedInitSegment);
          }
        }

        const currentSourceBuffer = sourceBufferRef.current;
        if (!currentSourceBuffer) {
          return;
        }

        // Drain queue once SourceBuffer is ready (initial append)
        if (videoQueueRef.current.length > 0 && !currentSourceBuffer.updating) {
          const chunk = videoQueueRef.current.shift();
          if (chunk) {
            try {
              currentSourceBuffer.appendBuffer(chunk);
            } catch (e) {
              setError("Error setting video stream");
            }
          }
        }

        currentSourceBuffer.addEventListener("updateend", () => {
          const sb = sourceBufferRef.current;
          const ms = mseRef.current;
          if (!sb || !ms) return;

          // Play once we have data appended
          if (videoElement.paused) {
            videoElement.play().catch((e) => {
              setError("Error playing video");
            });
          }

          // --- Inform browser of live stream for low-latency paths ---
          if (ms.readyState === 'open' && videoElement.buffered.length > 0) {
            try {
              const end = videoElement.buffered.end(videoElement.buffered.length - 1);
              ms.setLiveSeekableRange(0, end);
            } catch (e) {
              // Ignore if not supported or invalid state
            }
          }

          // --- Explicitly remove unneeded data from the buffer ---
          // We keep 1 second of history to prevent playback stalls, but aggressively remove older data.
          if (!sb.updating && videoElement.currentTime > 2) {
            try {
              if (videoElement.buffered.length > 0) {
                const start = videoElement.buffered.start(0);
                const endToRemove = videoElement.currentTime - 1;
                if (endToRemove > start) {
                  sb.remove(start, endToRemove);
                  return; // updateend will fire again when remove completes
                }
              }
            } catch (e) {
              // Ignore remove errors
            }
          }

          // Process next chunk in queue
          if (videoQueueRef.current.length > 0 && !sb.updating) {
            const chunk = videoQueueRef.current.shift();
            if (chunk) {
              try {
                sb.appendBuffer(chunk);
              } catch (e) {
                setError("Error setting video stream");
              }
            }
          }
        });
      } catch (e: any) {
        setError('Failed to initialize video stream.');
      }
    });
  }, []);

  const renderLoop = useCallback(() => {
    if (videoRef.current && canvasRef.current) {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');

      // --- Latency Check ---
      // Check if we are tracking 3 seconds of audible video playback
      if (trackingAvatarAudioRef.current && videoAnalyserRef.current) {
        if (avatarAudioStartPlayheadRef.current === null) {
          const dataArray = new Float32Array(videoAnalyserRef.current.fftSize);
          videoAnalyserRef.current.getFloatTimeDomainData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) {
            sum += dataArray[i] * dataArray[i];
          }
          const rms = Math.sqrt(sum / dataArray.length);
          
          if (rms > 0.02) {
            avatarAudioStartPlayheadRef.current = video.currentTime;
            avatarAudioStartPlayheadSystemTimeRef.current = performance.now();
          }
        } else if (video.currentTime - avatarAudioStartPlayheadRef.current >= 3) {
          if (avatarAudioStartPlayheadSystemTimeRef.current !== null && lastUserSpeechTimeRef.current > 0) {
            latencyRef.current = avatarAudioStartPlayheadSystemTimeRef.current - lastUserSpeechTimeRef.current;
          }
          trackingAvatarAudioRef.current = false; // Stop tracking until next user input
          avatarAudioStartPlayheadRef.current = null;
          avatarAudioStartPlayheadSystemTimeRef.current = null;
        }
      }

      // Draw if we have enough data (HAVE_CURRENT_DATA or higher) and video is playing
      if (ctx && video.readyState >= 2 && !video.paused) {
        if (video.videoWidth > 0) {
          if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
          }
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        }

        // --- Enforce maximum 500ms forward buffer latency for video ---
        if (video.buffered.length > 0) {
          const bufferedEnd = video.buffered.end(video.buffered.length - 1);
          const latency = bufferedEnd - video.currentTime;
          if (latency > 0.5) {
            // Jump close to the live edge but maintain a small buffer to prevent immediate stutter
            video.currentTime = bufferedEnd - 0.25;
          }
        }
      }
    }
    animationFrameRef.current = requestAnimationFrame(renderLoop);
  }, []);

  const disconnect = useCallback(() => {
    setIsConnected(false);
    setIsConnecting(false);
    setIsWaitingForVideo(false);
    setHasVideo(false);
    hasReceivedVideoRef.current = false;
    
    userHasSpokenForNextTurnRef.current = false;
    trackingAvatarAudioRef.current = false;
    avatarAudioStartPlayheadRef.current = null;
    avatarAudioStartPlayheadSystemTimeRef.current = null;
    latencyRef.current = 0;
    setDebugStats({
      buffered: 0,
      droppedFrames: 0,
      duration: 0,
      latency: 0,
    });
    activeSessionRef.current = null;

    if (sessionPromiseRef.current) {
      sessionPromiseRef.current.then(session => {
        try {
          session.close();
        } catch (e) {
          setError("Failed to close session");
        }
      });
      sessionPromiseRef.current = null;
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }

    if (scriptProcessorRef.current) {
      scriptProcessorRef.current.disconnect();
      scriptProcessorRef.current = null;
    }

    if (mediaSourceRef.current) {
      mediaSourceRef.current.disconnect();
      mediaSourceRef.current = null;
    }

    if (inputAudioContextRef.current) {
      inputAudioContextRef.current.close();
      inputAudioContextRef.current = null;
    }

    // Clear MSE and Video
    videoQueueRef.current = [];
    cachedInitSegmentRef.current = null;
    if (mseRef.current && mseRef.current.readyState === 'open') {
      try {
        mseRef.current.endOfStream();
      } catch (e) {setError("Failed to end stream")}
    }
    if (videoRef.current) {
      videoRef.current.pause();
      if (videoRef.current.src && videoRef.current.src.startsWith('blob:')) {
        URL.revokeObjectURL(videoRef.current.src);
      }
      videoRef.current.removeAttribute('src');
      videoRef.current.load();
    }
    sourceBufferRef.current = null;
    mseRef.current = null;

    // Clear canvas
    if (canvasRef.current) {
      const ctx = canvasRef.current.getContext('2d');
      if (ctx) {
        ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
      }
    }
  }, []);

  const connect = useCallback(async () => {
    if (isConnected || isConnecting) return;

    setIsConnecting(true);
    setIsWaitingForVideo(true);
    setError(null);
    setHasVideo(false);
    hasReceivedVideoRef.current = false;
    
    userHasSpokenForNextTurnRef.current = false;
    trackingAvatarAudioRef.current = false;
    avatarAudioStartPlayheadRef.current = null;
    avatarAudioStartPlayheadSystemTimeRef.current = null;
    latencyRef.current = 0;
    activeSessionRef.current = null;

    try {
      const ai = new GoogleGenAI({ apiKey: process.env.API_KEY, vertexai: true });
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : true
      });

      // Apply initial mute state
      stream.getAudioTracks().forEach(track => track.enabled = !isMuted);
      streamRef.current = stream;

      const inputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
      inputAudioContextRef.current = inputAudioContext;

      if (outputAudioContextRef.current?.state === 'suspended') {
        await outputAudioContextRef.current.resume();
      }

      // Reset video queue and init segment on new connection
      videoQueueRef.current = [];
      cachedInitSegmentRef.current = null;

      // Start the render loop for drawing video to canvas
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      renderLoop();

      // Function to start listening to audio input ONLY after video arrives
      const startAudioInput = () => {
        if (scriptProcessorRef.current || !inputAudioContextRef.current || !streamRef.current) return;

        const source = inputAudioContextRef.current.createMediaStreamSource(streamRef.current);
        const scriptProcessor = inputAudioContextRef.current.createScriptProcessor(1024, 1, 1);

        scriptProcessor.onaudioprocess = (audioProcessingEvent) => {
          // Drop audio frames if the session isn't fully ready or video hasn't arrived yet.
          // This prevents buffering audio and sending it in a burst.
          if (!activeSessionRef.current || !hasReceivedVideoRef.current) return;

          const inputData = audioProcessingEvent.inputBuffer.getChannelData(0);
          
          // Simple VAD for latency tracking
          let sum = 0;
          for (let i = 0; i < inputData.length; i++) {
            sum += inputData[i] * inputData[i];
          }
          const rms = Math.sqrt(sum / inputData.length);
          if (rms > 0.01) {
            lastUserSpeechTimeRef.current = performance.now();
            userHasSpokenForNextTurnRef.current = true;
          }

          const pcmBlob = createBlob(inputData);
          activeSessionRef.current.sendRealtimeInput({ media: pcmBlob });
        };

        source.connect(scriptProcessor);
        scriptProcessor.connect(inputAudioContextRef.current.destination);

        mediaSourceRef.current = source;
        scriptProcessorRef.current = scriptProcessor;
      };

      const sessionPromise = ai.live.connect({
        model: liveServiceConfiguration.model || LIVE_API_MODEL_NAME,
        callbacks: {
          onopen: () => {
            setIsConnected(true);
            setIsConnecting(false);
            // Note: We DO NOT start audio input here. We wait for the first video chunk.
          },
          onmessage: async (message: LiveServerMessage) => {
            const parts = message.serverContent?.modelTurn?.parts;

            if (parts) {
              for (const part of parts) {
                if (part.inlineData) {
                  const mimeType = part.inlineData.mimeType;
                  const base64Data = part.inlineData.data;

                  // Handle MP4 Video Chunks via MSE
                  if (mimeType.startsWith('video/mp4')) {
                    if (userHasSpokenForNextTurnRef.current) {
                      trackingAvatarAudioRef.current = true;
                      userHasSpokenForNextTurnRef.current = false; // Reset for next time
                      avatarAudioStartPlayheadRef.current = null;
                      avatarAudioStartPlayheadSystemTimeRef.current = null;
                    }

                    if (!hasReceivedVideoRef.current) {
                      hasReceivedVideoRef.current = true;
                      startAudioInput(); // Start listening to mic now that video has arrived
                    }
                    setHasVideo(true);
                    setIsWaitingForVideo(false);
                    initMediaSource();

                    const uint8Array = decode(base64Data);
                    const arrayBuffer = uint8Array.buffer.slice(uint8Array.byteOffset, uint8Array.byteOffset + uint8Array.byteLength);

                    if (!cachedInitSegmentRef.current) {
                      cachedInitSegmentRef.current = arrayBuffer;
                    }

                    const sourceBuffer = sourceBufferRef.current;
                    if (sourceBuffer && !sourceBuffer.updating && videoQueueRef.current.length === 0) {
                      try {
                        sourceBuffer.appendBuffer(arrayBuffer);
                      } catch (e: any) {
                        if (e.name === "InvalidStateError") {
                          mseRef.current = null;
                          sourceBufferRef.current = null;
                          videoQueueRef.current = [];
                          setError("MediaSource Invalid State");
                        } else {
                          videoQueueRef.current.push(arrayBuffer);
                        }
                      }
                    } else {
                      videoQueueRef.current.push(arrayBuffer);
                    }
                  }
                }
              }
            }
          },
          onerror: (e: ErrorEvent) => {
            setError('A connection error occurred.');
            disconnect();
          },
          onclose: (e: CloseEvent) => {
            disconnect();
          },
        },
        config: {
          avatarConfig: liveServiceConfiguration.avatarConfig as any,
          speechConfig: liveServiceConfiguration.generationConfig.speechConfig as any,
          responseModalities: liveServiceConfiguration.generationConfig.responseModalities as any,
          systemInstruction: liveServiceConfiguration.systemInstruction as any,
          inputAudioTranscription: liveServiceConfiguration.inputAudioTranscription as any,
          outputAudioTranscription: liveServiceConfiguration.outputAudioTranscription as any,
          tools: liveServiceConfiguration.tools as any,
        },
      });

      sessionPromiseRef.current = sessionPromise;
      sessionPromise.then(session => {
        activeSessionRef.current = session;
      }).catch(err => {
        // Error handled in main catch block
      });

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to access microphone or connect to API.';
      setError(errorMessage);
      disconnect();
    }
  }, [isConnected, isConnecting, disconnect, initMediaSource, renderLoop, selectedDeviceId, isMuted]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // @ts-ignore - liveServiceConfiguration might not have avatarConfig typed properly
  const avatarData = liveServiceConfiguration.avatarConfig?.customizedAvatar?.imageData || '';
  // @ts-ignore
  const avatarMime = liveServiceConfiguration.avatarConfig?.customizedAvatar?.imageMimeType || 'image/png';
  // @ts-ignore
  const avatarName = liveServiceConfiguration.avatarConfig?.avatarName || '';

  let avatarSrc = 'https://picsum.photos/800/600';
  if (avatarData) {
    avatarSrc = `data:${avatarMime};base64,${avatarData}`;
  } else if (avatarName) {
    avatarSrc = `https://www.gstatic.com/pantheon/images/aiplatform/vertex_ai_studio/avatars/${avatarName.toLowerCase()}.png`;
  }

  const isLoading = isConnecting || isWaitingForVideo;

  return (
    <div className="relative w-full h-screen overflow-hidden bg-gray-50 dark:bg-gray-950 transition-colors duration-300 flex flex-col items-center justify-center gap-4 pb-6 pt-12">

      {/* Debug Panel Toggle */}
      <div className="absolute top-6 left-6 z-50">
        <button
          onClick={() => setShowDebug(!showDebug)}
          className="p-2 bg-white/90 dark:bg-black/60 backdrop-blur-md rounded-full border border-gray-200 dark:border-white/10 shadow-sm text-gray-700 dark:text-white hover:bg-gray-100 dark:hover:bg-white/10 transition-colors"
          title="Toggle Debug Panel"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
        </button>
      </div>

      {/* Debug Panel Overlay */}
      {showDebug && (
        <div className="absolute top-20 left-6 z-50 bg-black/80 text-green-400 font-mono text-xs p-4 rounded-lg shadow-lg backdrop-blur-sm border border-green-500/30 flex flex-col gap-2 min-w-[220px] pointer-events-none">
          <div className="font-bold text-white mb-1 border-b border-green-500/30 pb-1">Playback Stats</div>
          <div className="flex justify-between"><span>Video Duration:</span> <span>{debugStats.duration.toFixed(2)}s</span></div>
          <div className="flex justify-between"><span>Buffer Ahead:</span> <span>{debugStats.buffered.toFixed(2)}s</span></div>
          <div className="flex justify-between"><span>Dropped Frames:</span> <span>{debugStats.droppedFrames}</span></div>
          <div className="flex justify-between"><span>Response Latency:</span> <span>{debugStats.latency > 0 ? `${debugStats.latency.toFixed(0)}ms` : '-'}</span></div>
        </div>
      )}

      {/* Theme Toggle */}
      <div className="absolute top-6 right-6 z-50">
        <div className="flex items-center gap-2 bg-white/90 dark:bg-black/60 backdrop-blur-md px-3 py-1.5 rounded-full border border-gray-200 dark:border-white/10 shadow-sm transition-colors">
          {theme === 'dark' ? (
            <svg className="w-4 h-4 text-gray-500 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" /></svg>
          ) : theme === 'light' ? (
            <svg className="w-4 h-4 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" /></svg>
          ) : (
            <svg className="w-4 h-4 text-gray-500 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
          )}
          <select
            value={theme}
            onChange={(e) => setTheme(e.target.value as Theme)}
            className="bg-transparent text-sm font-medium text-gray-700 dark:text-gray-200 outline-none cursor-pointer appearance-none pr-4"
          >
            <option value="system" className="bg-white dark:bg-gray-900 text-gray-900 dark:text-white">System</option>
            <option value="light" className="bg-white dark:bg-gray-900 text-gray-900 dark:text-white">Light</option>
            <option value="dark" className="bg-white dark:bg-gray-900 text-gray-900 dark:text-white">Dark</option>
          </select>
          <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none">
            <svg className="w-3 h-3 text-gray-500 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
          </div>
        </div>
      </div>

      {/* Main Video Container */}
      <div className={`relative transition-all duration-500 rounded-3xl overflow-hidden flex-shrink-0 bg-gray-50 dark:bg-gray-950 ${isConnected ? 'shadow-[0_0_40px_rgba(34,197,94,0.2)]' : 'shadow-lg'}`}
           style={{ 
             width: '100%',
             maxWidth: `min(85vw, 70%, 80vh * ${aspectRatio})`,
             aspectRatio: aspectRatio
           }}>

        {/* Video Canvas (for JPEG frames and MP4 rendering) */}
        <canvas
          ref={canvasRef}
          className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-500 ${hasVideo ? 'opacity-100' : 'opacity-0'}`}
        />

        {/* Hidden MP4 Video Element used as source for canvas via MSE. */}
        <video
          ref={videoRef}
          className="absolute w-[1px] h-[1px] opacity-0 pointer-events-none -z-10"
          playsInline
          autoPlay
        />

        {/* Static Avatar Image - Dictates container size */}
        <img
          src={avatarSrc}
          alt="AI Avatar"
          onLoad={(e) => {
            const { naturalWidth, naturalHeight } = e.currentTarget;
            if (naturalWidth && naturalHeight) {
              setAspectRatio(naturalWidth / naturalHeight);
            }
          }}
          className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-500 ${hasVideo ? 'opacity-0' : 'opacity-100'}`}
        />

        {/* Status Indicator (Positioned at the bottom of the avatar) */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-2.5 bg-black/60 backdrop-blur-md px-4 py-2 rounded-full shadow-sm z-50 pointer-events-none">
          <div className={`w-2.5 h-2.5 rounded-full ${
            error ? 'bg-red-500' :
            isLoading ? 'bg-yellow-500 animate-pulse shadow-[0_0_8px_rgba(234,179,8,0.8)]' :
            isConnected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.8)]' :
            'bg-gray-400'
          }`}></div>
          <span className="text-sm font-medium text-white whitespace-nowrap">
            {error ? <span className="text-red-400">{error}</span> :
             isLoading ? 'Connecting...' :
             isConnected ? 'Connected' : 'Ready to connect'}
          </span>
        </div>
      </div>

      {/* Controls Container (Moved outside and below the video container) */}
      <div className="flex flex-col items-center gap-2 z-50 w-full max-w-md px-4 mt-2">

        {/* Action Button */}
        <button
          onClick={isConnected ? disconnect : connect}
          disabled={isConnecting}
          className={`flex items-center justify-center gap-2 px-5 py-2 rounded-full font-bold text-sm transition-all duration-300 transform hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none shadow-md
            ${isConnected
              ? 'bg-red-500 hover:bg-red-600 text-white border border-red-400/50'
              : 'bg-blue-600 hover:bg-blue-700 text-white border border-blue-400/50'
             }`}>
          {isLoading ? (
            <>
              <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              {isConnected ? 'End Conversation' : 'Connecting...'}
            </>
          ) : isConnected ? (
            'End Conversation'
          ) : (
            'Start Conversation'
          )}
        </button>

        {/* Device Controls Row */}
        <div className="flex items-center justify-center gap-2">
          {/* Mic Controls */}
          <div className="flex items-center bg-white dark:bg-gray-800 rounded-full border border-gray-200 dark:border-gray-700 shadow-sm">
            <button
              onClick={toggleMute}
              className={`p-2 rounded-l-full transition-colors ${isMuted ? 'bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20' : 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'}`}
              title={isMuted ? "Unmute" : "Mute"}
            >
              {isMuted ? (
                <svg className="w-3.5 h-3.5" viewBox="0 0 18 18" aria-hidden="true" fill="currentColor">
                  <path fillRule="evenodd" d="m11.023 8.613.007-4.417C11.03 2.974 10.12 2 8.98 2s-1.983.974-1.983 2.196v4.417c0 1.222.843 2.124 1.984 2.124 1.14 0 2.042-.902 2.042-2.124m-2.014 3.441c-1.896.095-3.641-1.725-3.641-3.934H4.2c0 2.51 1.868 4.883 4.153 5.244V16h1.311v-2.636c2.285-.354 4.153-2.726 4.153-5.244h-1.168c0 2.209-1.745 4.029-3.64 3.934"></path>
                  <line x1="2" y1="2" x2="16" y2="16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" viewBox="0 0 18 18" aria-hidden="true" fill="currentColor">
                  <path fillRule="evenodd" d="m11.023 8.613.007-4.417C11.03 2.974 10.12 2 8.98 2s-1.983.974-1.983 2.196v4.417c0 1.222.843 2.124 1.984 2.124 1.14 0 2.042-.902 2.042-2.124m-2.014 3.441c-1.896.095-3.641-1.725-3.641-3.934H4.2c0 2.51 1.868 4.883 4.153 5.244V16h1.311v-2.636c2.285-.354 4.153-2.726 4.153-5.244h-1.168c0 2.209-1.745 4.029-3.64 3.934"></path>
                </svg>
              )}
            </button>
            <div className="w-px h-3 bg-gray-200 dark:bg-gray-700"></div>
            <div className="relative p-2 rounded-r-full hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors cursor-pointer flex items-center justify-center">
              <select
                value={selectedDeviceId}
                onChange={handleDeviceChange}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                title="Select Microphone"
              >
                {audioDevices.length === 0 && <option value="">Default Microphone</option>}
                {audioDevices.map(device => (
                  <option key={device.deviceId} value={device.deviceId} className="bg-white dark:bg-gray-900 text-gray-900 dark:text-white">
                    {device.label || `Microphone ${device.deviceId.slice(0, 5)}...`}
                  </option>
                ))}
              </select>
              <svg className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </div>

          {/* Speaker Controls */}
          <div className="flex items-center bg-white dark:bg-gray-800 rounded-full border border-gray-200 dark:border-gray-700 shadow-sm">
            <div className="p-2 rounded-l-full text-gray-600 dark:text-gray-300">
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" preserveAspectRatio="xMidYMid meet" focusable="false" fill="currentColor">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"></path>
              </svg>
            </div>
            <div className="w-px h-3 bg-gray-200 dark:bg-gray-700"></div>
            <div className="relative p-2 rounded-r-full hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors cursor-pointer flex items-center justify-center">
              <select
                value={selectedAudioOutputId}
                onChange={handleAudioOutputChange}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                title="Select Speaker"
              >
                {audioOutputDevices.length === 0 && <option value="">Default Speaker</option>}
                {audioOutputDevices.map(device => (
                  <option key={device.deviceId} value={device.deviceId} className="bg-white dark:bg-gray-900 text-gray-900 dark:text-white">
                    {device.label || `Speaker ${device.deviceId.slice(0, 5)}...`}
                  </option>
                ))}
              </select>
              <svg className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;